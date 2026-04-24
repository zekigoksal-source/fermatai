"""
Zeki Göksal'i ACL tablosuna admin olarak ekler.
Çalıştır: python add_admin.py +905XXXXXXXXX
"""
import asyncio, asyncpg, os, sys, pathlib
from dotenv import load_dotenv

_here = pathlib.Path(__file__).parent
load_dotenv(_here / "eyotek_agent" / ".env")

async def main():
    if len(sys.argv) < 2:
        print("Kullanım: python add_admin.py +905XXXXXXXXX")
        print("Örnek:    python add_admin.py +905321234567")
        return

    phone = sys.argv[1].strip().replace(" ","").replace("-","")
    if not phone.startswith("+"):
        phone = "+" + phone

    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))

    # acl_users tablosunu oluştur (yoksa)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS acl_users (
            id          SERIAL PRIMARY KEY,
            phone       TEXT NOT NULL UNIQUE,
            full_name   TEXT,
            role        TEXT NOT NULL DEFAULT 'guest',
            eyotek_id   TEXT,
            class_scope TEXT[],
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes       TEXT
        )
    """)

    await conn.execute("""
        INSERT INTO acl_users (phone, full_name, role, eyotek_id, is_active, notes)
        VALUES ($1, 'ZEKİ GÖKSAL', 'admin', '1035', TRUE, 'Kurucu admin')
        ON CONFLICT (phone) DO UPDATE SET
            role      = 'admin',
            full_name = 'ZEKİ GÖKSAL',
            eyotek_id = '1035',
            is_active = TRUE,
            updated_at = CURRENT_TIMESTAMP
    """, phone)

    row = await conn.fetchrow("SELECT * FROM acl_users WHERE phone = $1", phone)
    print(f"\n✅ Admin eklendi:")
    print(f"   Phone:     {row['phone']}")
    print(f"   Ad:        {row['full_name']}")
    print(f"   Rol:       {row['role']}")
    print(f"   Eyotek ID: {row['eyotek_id']}")

    await conn.close()

asyncio.run(main())
