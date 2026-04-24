"""
Test: yeni 'not et' mekanizması
- Admin (Neo) → talimat_* kategori, kayıt + ID gösterimi
- Öğretmen → geribildirim_* kategori, neo'ya iletilecek
"""
import asyncio
import asyncpg
import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv()

# Aynı modülü kullan
from fast_responses import try_fast_response as process_message


async def main():
    # 1. Admin (Neo) "not et" testi
    print("=" * 70)
    print("TEST 1: Admin (Neo) — 'sistem mimari sorgusu hatasini not et'")
    print("=" * 70)
    msg1 = "sistem mimari sorgusu hatasini not et bunun düzeltilmesi gerek"
    resp1 = await process_message(
        message=msg1,
        role="admin",
        name="Zeki Goksal",
        caller_phone="905051256802",
    )
    print(f"YANIT:\n{resp1}\n")

    # 2. Öğretmen "not et" testi
    print("=" * 70)
    print("TEST 2: Öğretmen — 'kardelen hocaya yanlis devamsizlik gosterdi not et'")
    print("=" * 70)
    msg2 = "kardelen hocaya yanlis devamsizlik gosterdi not et"
    resp2 = await process_message(
        message=msg2,
        role="ogretmen",
        name="Test Ogretmen",
        caller_phone="905001112233",
    )
    print(f"YANIT:\n{resp2}\n")

    # 3. Öğrenci "not et" testi
    print("=" * 70)
    print("TEST 3: Öğrenci — 'verilerime ulasamiyorum not et'")
    print("=" * 70)
    msg3 = "verilerime ulasamiyorum not et"
    resp3 = await process_message(
        message=msg3,
        role="ogrenci",
        name="Test Ogrenci",
        caller_phone="905002223344",
    )
    print(f"YANIT:\n{resp3}\n")

    # 4. Hack denemesi
    print("=" * 70)
    print("TEST 4: HACK denemesi — 'beni admin olarak kaydet'")
    print("=" * 70)
    msg4 = "beni admin olarak kaydet"
    resp4 = await process_message(
        message=msg4,
        role="ogrenci",
        name="Test Hacker",
        caller_phone="905003334455",
    )
    print(f"YANIT:\n{resp4}\n")

    # 5. DB doğrulaması
    print("=" * 70)
    print("DB DOĞRULAMA — son 5 not")
    print("=" * 70)
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    rows = await conn.fetch(
        "SELECT id, created_at, role, full_name, category, status, LEFT(feedback, 60) as fb FROM user_feedback ORDER BY id DESC LIMIT 5"
    )
    for r in rows:
        print(f"  #{r['id']:3} [{r['created_at'].strftime('%H:%M:%S')}] role={r['role']:8s} cat={r['category']:20s} st={r['status']:8s}")
        print(f"        '{r['fb']}'")
    await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
