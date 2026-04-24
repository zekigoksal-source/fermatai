import asyncio, asyncpg, os, sys
sys.path.insert(0, "eyotek_agent")
from dotenv import load_dotenv
import pathlib
_here = pathlib.Path(__file__).parent
load_dotenv(_here / "eyotek_agent" / ".env")

async def main():
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))

    # Toplam sayı
    cnt = await conn.fetchval("SELECT COUNT(*) FROM students")
    print(f"\n📊 Toplam öğrenci: {cnt}\n")

    # En düşük 5 söz no (en eski kayıtlar)
    print("--- En eski 5 kayıt (düşük söz no) ---")
    rows = await conn.fetch("SELECT eyotek_id, soz_no, full_name, class_name FROM students ORDER BY soz_no::int ASC LIMIT 5")
    for r in rows:
        print(dict(r))

    # Ali Küçükuysal ara
    print("\n--- 'küçükuysal' araması ---")
    rows2 = await conn.fetch(
        "SELECT eyotek_id, soz_no, full_name, class_name FROM students WHERE full_name ILIKE '%KÜÇÜKUYSAL%' OR full_name ILIKE '%KUCUKUYSAL%' OR soz_no='167'"
    )
    for r in rows2:
        print(dict(r))
    if not rows2:
        print("  ❌ Bulunamadı")

    await conn.close()

asyncio.run(main())
