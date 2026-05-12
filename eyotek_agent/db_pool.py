"""
Merkezi DB Bağlantı Havuzu — TÜM dosyalar buradan kullanır.

Kullanım:
    from db_pool import get_pool, db_url
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ...")

    # Veya kısa yollar:
    from db_pool import db_fetch, db_fetchrow, db_fetchval, db_execute
    rows = await db_fetch("SELECT * FROM students LIMIT 5")
    row = await db_fetchrow("SELECT * FROM students WHERE soz_no=$1", 230)
    val = await db_fetchval("SELECT COUNT(*) FROM students")
    await db_execute("UPDATE ... SET ... WHERE ...")
"""
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

# TEK DSN — tüm proje buradan okur. .env'de POSTGRES_URL veya DATABASE_URL
# OTURUM 22.1 (21 Nisan) — hardcoded password fallback kaldirildi (guvenlik)
DB_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError(
        "DATABASE_URL / POSTGRES_URL tanimli degil. "
        ".env dosyasinda DATABASE_URL=postgresql://... olarak ayarla."
    )

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None  # lazy init (event loop bekler)


def _is_pool_closed(p) -> bool:
    """Pool kapalı mı — asyncpg API farklarına dayanıklı kontrol.

    25.44 BUG FIX (bot dev meeting #4, 12 May 19:35):
    Eski `p._closed` private attr — asyncpg sürümleri arasında değişebilir.
    Public API yöntemi: `is_closing()` veya state kontrol.
    """
    if p is None:
        return True
    # Önce public API dene
    for method in ('is_closing', 'is_closed'):
        fn = getattr(p, method, None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                pass
    # Fallback: private attrs (asyncpg internal)
    for attr in ('_closed', '_closing'):
        if hasattr(p, attr):
            try:
                return bool(getattr(p, attr))
            except Exception:
                pass
    return False


async def get_pool(min_size: int = 3, max_size: int = 20) -> asyncpg.Pool:
    """Paylaşımlı connection pool döner. Lazy init — ilk çağrıda oluşturulur.

    25.40r — Workers=3 hazirligi:
    Her worker kendi pool'unu olusturur (process izolasyonu, paylasilmaz).
    3 worker × max=20 = 60 max conn (Postgres default max_connections=100, guvenli).
    3 worker × min=3 = 9 idle (warmup).
    Bellek: 60 conn × ~10MB = 600MB (VPS 13GB serbest).

    25.44 BUG FIX (bot dev meeting #4): Race condition + exception reset.
    Sentry #116911596 'Connection closed while reading' — bugün 12:07.
    Eski kod: race kondisyonunda iki pool yaratılabilir, exception sonrası
    bozuk _pool kalıyordu. Şimdi: double-check lock + exception reset.

    25.23-final: 120 ogrenci pikta 50+ concurrent query olabilir
    """
    global _pool, _pool_lock
    # Fast path — lock'suz (zaten init edilmiş ve açık)
    if _pool is not None and not _is_pool_closed(_pool):
        return _pool
    # Slow path — lock altında double-check
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    async with _pool_lock:
        if _pool is None or _is_pool_closed(_pool):
            try:
                _pool = await asyncpg.create_pool(
                    DB_URL, min_size=min_size, max_size=max_size
                )
            except Exception:
                _pool = None  # reset — sonraki çağrı yeniden dener
                raise
        return _pool


async def close_pool():
    """Uygulama kapanırken pool'u kapat."""
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        _pool = None


# ── Kısa yol helper'lar ──────────────────────────────────────────────────────

async def db_fetch(sql: str, *args) -> list[dict]:
    """SELECT sorgusu çalıştır, liste döner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]


async def db_fetchrow(sql: str, *args) -> dict | None:
    """Tek satır döner veya None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *args)
        return dict(row) if row else None


async def db_fetchval(sql: str, *args):
    """Tek değer döner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def db_execute(sql: str, *args) -> str:
    """INSERT/UPDATE/DELETE çalıştır, status string döner."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)
