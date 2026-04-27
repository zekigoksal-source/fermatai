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


async def get_pool(min_size: int = 5, max_size: int = 30) -> asyncpg.Pool:
    """Paylaşımlı connection pool döner. Lazy init — ilk çağrıda oluşturulur.

    25.23-final: 120 ogrenci pikta 50+ concurrent query olabilir
    Eski max=10 → 'no available connection' riski (Eylul senaryosunda)
    Yeni max=30 + min=5 (warmup) — Postgres default max_connections=100, rahat.
    Bellek: 30 connection × ~10MB = 300MB (VPS 13GB serbest).
    """
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(DB_URL, min_size=min_size, max_size=max_size)
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
