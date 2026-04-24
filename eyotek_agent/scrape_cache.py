"""
Eyotek Scrape Cache Katmanı (22.1n-fikir5)
===========================================

Neo 20 Nisan 12:49 stratejik:
> "Eyotek api desteği olmazsa zamanla su otomasyona adapte olamadıkları içinde yok
>  olurlar demode kalırlar"

API yoksa: Playwright scrape ile hayatta kalmalıyız. En büyük iki sorun:
1. Her istek yeni sayfa yükleme → 5-15s gecikme
2. Eyotek session drop → işlem patlar

ÇÖZÜM: Akıllı cache + additive fallback
- Eyotek'ten çekilen veri → `scrape_cache` tablosuna + TTL
- Aynı operation aynı params ile tekrar istenince → DB'den hızlı cevap
- Eyotek offline ise → expired cache de dönebilir (best-effort)

KULLANIM:
  from scrape_cache import cached

  @cached(operation="student_grades", ttl_seconds=600)
  async def scrape_student_grades(soz_no):
      # Eyotek scrape...

veya explicit:
  from scrape_cache import get_cached, set_cache
  key = make_key("student_grades", {"soz_no": 174})
  hit = await get_cached(key)
  if hit:
      return hit
  data = await scrape_actually()
  await set_cache(key, data, ttl_seconds=600)
  return data

GÜVENLİK (22.1n-kural1):
- Bu modül ASLA mesaj göndermez. Sadece DB read/write.
- Cache verileri PII içerebilir — `acl_users` + `students` gibi tablolar kullanılıyorsa sadece sunucu içi.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Optional

from loguru import logger


CACHE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scrape_cache (
    cache_key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    params_hash TEXT,
    result JSONB,
    stale_ok BOOLEAN DEFAULT FALSE,
    hit_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    last_hit_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_scrape_cache_op ON scrape_cache(operation, expires_at DESC);
"""


async def init_db():
    """Cache tablosu hazırla (idempotent)."""
    from db_pool import db_execute
    await db_execute(CACHE_TABLE_SQL)


def make_key(operation: str, params: dict | None = None) -> str:
    """Deterministic cache key — aynı params + aynı op = aynı key."""
    p_str = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.md5(p_str.encode("utf-8")).hexdigest()[:16]
    return f"{operation}:{h}"


async def get_cached(key: str, allow_stale: bool = False) -> Optional[Any]:
    """Cache'ten oku. Expired ise None (allow_stale=True ise expired da dönebilir).
    22.1n-neo: Finans key'leri CACHE READ de yapilmaz (zaten yaz da yasak)."""
    # Key formati: 'operation:hash' → operation parcasini extract
    try:
        op_part = (key or "").split(":", 1)[0]
        from finans_access import is_finans_cache_op
        if is_finans_cache_op(op_part):
            return None
    except Exception:
        pass
    from db_pool import db_fetchrow, db_execute
    try:
        row = await db_fetchrow(
            """SELECT result, expires_at, hit_count FROM scrape_cache
               WHERE cache_key=$1""",
            key,
        )
        if not row:
            return None
        expires = row["expires_at"]
        now = datetime.now()
        if expires and now > expires and not allow_stale:
            return None
        # Hit count + last_hit_at güncelle (fire-and-forget olsun istersek async create_task)
        try:
            await db_execute(
                "UPDATE scrape_cache SET hit_count=hit_count+1, last_hit_at=NOW() WHERE cache_key=$1",
                key,
            )
        except Exception:
            pass
        result = row["result"]
        # JSON string ise decode et
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except Exception:
                pass
        return result
    except Exception as e:
        logger.debug(f"get_cached err: {e}")
        return None


async def set_cache(key: str, operation: str, params: dict | None,
                    result: Any, ttl_seconds: int = None):
    """Cache'e yaz. 22.1n-neo: default TTL config.py'den (CACHE_TTL_HOT_SEC).
    FINANS operation'lari CACHE'E YAZILMAZ (plaintext disk sizma riski)."""
    # 22.1n-neo: Finans cache DENY
    try:
        from finans_access import is_finans_cache_op
        if is_finans_cache_op(operation):
            return  # SESSIZCE atla — cache yok
    except Exception:
        pass
    if ttl_seconds is None:
        try:
            from config import CACHE_TTL_HOT_SEC
            ttl_seconds = CACHE_TTL_HOT_SEC
        except Exception:
            ttl_seconds = 600
    from db_pool import db_execute
    try:
        params_h = hashlib.md5(
            json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:16]
        expires = datetime.now() + timedelta(seconds=ttl_seconds)
        serialized = json.dumps(result, ensure_ascii=False, default=str)
        await db_execute(
            """INSERT INTO scrape_cache (cache_key, operation, params_hash, result, expires_at)
               VALUES ($1, $2, $3, $4::jsonb, $5)
               ON CONFLICT (cache_key) DO UPDATE SET
                 result = EXCLUDED.result,
                 expires_at = EXCLUDED.expires_at,
                 created_at = NOW()""",
            key, operation, params_h, serialized, expires,
        )
    except Exception as e:
        logger.debug(f"set_cache err: {e}")


def cached(operation: str, ttl_seconds: int = None, allow_stale_on_error: bool = True):
    """Decorator — async function'ı otomatik cache katmanıyla sar.

    operation: "student_grades" vb. — cache identifier
    ttl_seconds: freshness süre (default CACHE_TTL_HOT_SEC config.py'den)
    allow_stale_on_error: Scrape başarısızsa expired cache dönelim mi?
    22.1n-neo: TTL config.py'den merkezi (fallback 600s)
    """
    if ttl_seconds is None:
        try:
            from config import CACHE_TTL_HOT_SEC
            ttl_seconds = CACHE_TTL_HOT_SEC
        except Exception:
            ttl_seconds = 600
    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            # Params: positional + kw
            all_params = {"args": args, "kwargs": kwargs}
            key = make_key(operation, all_params)

            # Cache hit
            hit = await get_cached(key)
            if hit is not None:
                logger.debug(f"  [CACHE HIT] {operation} key={key[-8:]}")
                return hit

            # Miss — scrape
            try:
                result = await fn(*args, **kwargs)
                if result is not None:
                    await set_cache(key, operation, all_params, result, ttl_seconds)
                return result
            except Exception as e:
                logger.warning(f"  [SCRAPE FAIL] {operation}: {e}")
                if allow_stale_on_error:
                    stale = await get_cached(key, allow_stale=True)
                    if stale is not None:
                        logger.info(f"  [STALE CACHE served] {operation}")
                        return stale
                raise

        return wrapper
    return decorator


async def stats() -> dict:
    """Cache istatistikleri — admin diagnostic."""
    from db_pool import db_fetch, db_fetchrow
    r = await db_fetchrow(
        """SELECT COUNT(*) AS toplam,
                  COUNT(*) FILTER (WHERE expires_at > NOW()) AS aktif,
                  COALESCE(SUM(hit_count), 0) AS toplam_hit
           FROM scrape_cache"""
    )
    by_op = await db_fetch(
        """SELECT operation, COUNT(*) AS cnt, SUM(hit_count) AS hits
           FROM scrape_cache GROUP BY operation ORDER BY hits DESC LIMIT 10"""
    )
    return {
        "toplam": int(r["toplam"]) if r else 0,
        "aktif": int(r["aktif"]) if r else 0,
        "toplam_hit": int(r["toplam_hit"]) if r else 0,
        "operasyonlar": [{"op": x["operation"], "cnt": int(x["cnt"]), "hits": int(x["hits"] or 0)} for x in by_op],
    }


async def cleanup_expired(grace_days: int = 7):
    """Eski expired kayıtları temizle — grace period sonrası."""
    from db_pool import db_execute
    cutoff = datetime.now() - timedelta(days=grace_days)
    await db_execute(
        "DELETE FROM scrape_cache WHERE expires_at < $1",
        cutoff,
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────
async def main():
    import argparse, sys, io
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--cleanup", type=int, default=None, help="Grace days (ör 7)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(override=True)

    if args.init:
        await init_db()
        print("scrape_cache tablosu hazir")
    if args.stats:
        s = await stats()
        import json
        print(json.dumps(s, indent=2, ensure_ascii=False))
    if args.cleanup is not None:
        await cleanup_expired(grace_days=args.cleanup)
        print(f"Cleanup {args.cleanup} gun sonrası expired temizlendi")


if __name__ == "__main__":
    import io as _io, sys as _sys
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
