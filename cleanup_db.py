"""
DB'deki eski bozuk sync kayıtlarını temizle.
Çalıştır: python cleanup_db.py
"""
import asyncio, asyncpg, os, pathlib
from dotenv import load_dotenv

_here = pathlib.Path(__file__).parent
load_dotenv(_here / "eyotek_agent" / ".env")

async def main():
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))

    # Bozuk kayıtları önce göster
    bad = await conn.fetch(
        "SELECT eyotek_id, soz_no, full_name FROM students WHERE eyotek_id::int < 100 AND soz_no::int < 100"
    )
    if not bad:
        print("✅ Temizlenecek çöp kayıt yok.")
        await conn.close()
        return

    print(f"[TEMIZLIK] Silinecek {len(bad)} kayit:")
    for r in bad:
        print(f"  eyotek_id={r['eyotek_id']}  soz_no={r['soz_no']}  full_name={r['full_name']!r}")

    # Sil
    deleted = await conn.execute(
        "DELETE FROM students WHERE eyotek_id::int < 100 AND soz_no::int < 100"
    )
    print(f"\n✅ Silindi: {deleted}")

    cnt = await conn.fetchval("SELECT COUNT(*) FROM students")
    print(f"📊 Kalan öğrenci: {cnt}")
    await conn.close()

asyncio.run(main())
