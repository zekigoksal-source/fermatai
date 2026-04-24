"""
Hack/Jailbreak Attempt Tracker (Oturum 22.1d)
=============================================

DB-persistent jailbreak deneme sayaci. Bridge restart'ta SIFIRLANMAZ.

Tablo: hack_attempts
  phone, attempt_count, blocked_until, last_attempt_at

Ak is:
  - Kullanici jailbreak denerse → hack_log(phone) cagrilir, sayac++.
  - 5+ deneme → otomatik 1 saat blok (blocked_until NOW+1h).
  - is_hack_blocked(phone) → expired mi kontrol edip True/False.
  - Blok suresi bitince sayac 0'a sifirlanir (yeni pencere).

Eski in-memory _HACK_COUNTER (fast_responses.py) DEPRECATED — bu modul kullanilir.
"""
import asyncio
from typing import Optional
from loguru import logger


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS hack_attempts (
    phone TEXT PRIMARY KEY,
    attempt_count INT DEFAULT 1,
    blocked_until TIMESTAMP NULL,
    first_attempt_at TIMESTAMP DEFAULT NOW(),
    last_attempt_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hack_blocked_until ON hack_attempts (blocked_until);
"""

BLOCK_THRESHOLD = 5      # kac deneme sonrasi blok
BLOCK_MINUTES = 60       # blok suresi


async def init_db():
    """Tablo olustur."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    logger.info("hack_attempts tablosu hazir")


async def record_attempt(phone: str) -> dict:
    """
    Jailbreak denemesi kaydet. Threshold asilmissa blokla.

    Returns: {"count": int, "blocked": bool, "blocked_until": datetime|None}
    """
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Upsert — mevcut kaydi guncelle veya yeni ac
        row = await conn.fetchrow("""
            INSERT INTO hack_attempts (phone, attempt_count, last_attempt_at)
            VALUES ($1, 1, NOW())
            ON CONFLICT (phone) DO UPDATE SET
                attempt_count = hack_attempts.attempt_count + 1,
                last_attempt_at = NOW()
            RETURNING attempt_count, blocked_until
        """, phone)

        count = row["attempt_count"]
        blocked = False
        blocked_until = row["blocked_until"]

        # Threshold asildiysa blokla
        if count >= BLOCK_THRESHOLD:
            blocked = True
            row2 = await conn.fetchrow(f"""
                UPDATE hack_attempts
                SET blocked_until = NOW() + INTERVAL '{BLOCK_MINUTES} minutes'
                WHERE phone = $1
                RETURNING blocked_until
            """, phone)
            blocked_until = row2["blocked_until"]
            logger.warning(f"🚫 Hack blok: {phone} — {count} deneme, {BLOCK_MINUTES}dk blok")

    return {
        "count": count,
        "blocked": blocked,
        "blocked_until": blocked_until,
    }


async def is_hack_blocked(phone: str) -> bool:
    """Numara hack sebebiyle bloklu mu (expire olmamis)?"""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT blocked_until FROM hack_attempts
            WHERE phone = $1 AND blocked_until IS NOT NULL AND blocked_until > NOW()
        """, phone)
        return row is not None


async def reset_attempts(phone: str) -> bool:
    """Bir numaranin sayacini manuel sifirla (admin komutu)."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM hack_attempts WHERE phone = $1", phone)
    logger.info(f"Hack kayit silindi: {phone}")
    return True


async def cleanup_expired(days_keep: int = 7) -> int:
    """7 gunden eski (blocked_until gecmis veya NULL) kayitlari temizle."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(f"""
            DELETE FROM hack_attempts
            WHERE last_attempt_at < NOW() - INTERVAL '{days_keep} days'
            AND (blocked_until IS NULL OR blocked_until < NOW())
        """)
    try:
        count = int(result.split()[-1])
    except Exception:
        count = 0
    if count:
        logger.info(f"🧹 hack_attempts: {count} eski kayit silindi")
    return count


async def get_stats() -> dict:
    """Son 30 gun istatistik."""
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        toplam = await conn.fetchval("SELECT COUNT(*) FROM hack_attempts")
        aktif_blok = await conn.fetchval(
            "SELECT COUNT(*) FROM hack_attempts WHERE blocked_until > NOW()"
        )
        en_cok = await conn.fetch("""
            SELECT phone, attempt_count, blocked_until, last_attempt_at
            FROM hack_attempts
            ORDER BY attempt_count DESC LIMIT 10
        """)
    return {
        "toplam_phone": toplam,
        "aktif_blok": aktif_blok,
        "en_cok_deneyen": [dict(r) for r in en_cok],
    }
