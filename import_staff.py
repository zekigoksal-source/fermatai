"""
staff_export.json dosyasını PostgreSQL'e import eder.
Çalıştır: python import_staff.py
"""
import asyncio, asyncpg, json, os, pathlib
from dotenv import load_dotenv

_here = pathlib.Path(__file__).parent
load_dotenv(_here / "eyotek_agent" / ".env")

async def main():
    export_file = _here / "staff_export.json"
    if not export_file.exists():
        print("❌ staff_export.json bulunamadı!")
        return

    with open(export_file, encoding="utf-8") as f:
        staff_list = json.load(f)
    print(f"📊 {len(staff_list)} personel okundu")

    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))

    # Tablo oluştur (yoksa)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            eyotek_id   TEXT PRIMARY KEY,
            ik_no       TEXT,
            full_name   TEXT,
            first_name  TEXT,
            last_name   TEXT,
            gorev       TEXT,
            brans       TEXT,
            email       TEXT,
            kullanici   TEXT,
            sezon       TEXT,
            sube        TEXT,
            soz_tarihi  TEXT,
            cikis_tar   TEXT,
            status      TEXT DEFAULT 'Aktif',
            last_sync   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    saved = 0
    errors = 0
    for s in staff_list:
        eyotek_id  = s.get("eyotek_id", "").strip()
        first_name = s.get("first_name", "").strip()
        last_name  = s.get("last_name", "").strip()
        full_name  = f"{first_name} {last_name}".strip()
        if not eyotek_id:
            continue
        try:
            await conn.execute("""
                INSERT INTO staff (
                    eyotek_id, ik_no, full_name, first_name, last_name,
                    gorev, brans, email, kullanici,
                    sezon, sube, soz_tarihi, cikis_tar,
                    status, last_sync
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,CURRENT_TIMESTAMP)
                ON CONFLICT (eyotek_id) DO UPDATE SET
                    ik_no      = EXCLUDED.ik_no,
                    full_name  = EXCLUDED.full_name,
                    first_name = EXCLUDED.first_name,
                    last_name  = EXCLUDED.last_name,
                    gorev      = EXCLUDED.gorev,
                    brans      = EXCLUDED.brans,
                    email      = EXCLUDED.email,
                    kullanici  = EXCLUDED.kullanici,
                    sezon      = EXCLUDED.sezon,
                    sube       = EXCLUDED.sube,
                    soz_tarihi = EXCLUDED.soz_tarihi,
                    cikis_tar  = EXCLUDED.cikis_tar,
                    status     = EXCLUDED.status,
                    last_sync  = CURRENT_TIMESTAMP
            """,
                eyotek_id,
                s.get("ik_no", ""),
                full_name,
                first_name,
                last_name,
                s.get("gorev", ""),
                s.get("brans", ""),
                s.get("email", ""),
                s.get("kullanici", ""),
                s.get("sezon", ""),
                s.get("sube", ""),
                s.get("soz_tarihi", ""),
                s.get("cikis_tar", ""),
                "Aktif",
            )
            saved += 1
        except Exception as e:
            print(f"  ❌ {eyotek_id} {full_name}: {e}")
            errors += 1

    await conn.close()
    print(f"\n✅ Tamamlandı: {saved} kayıt, {errors} hata")

    # Doğrula
    conn2 = await asyncpg.connect(os.getenv("DATABASE_URL"))
    cnt  = await conn2.fetchval("SELECT COUNT(*) FROM staff")
    zeki = await conn2.fetchrow(
        "SELECT eyotek_id, full_name, brans FROM staff WHERE full_name ILIKE '%ZEKİ%' OR full_name ILIKE '%GÖKSAL%'"
    )
    print(f"\n--- Doğrulama ---")
    print(f"Toplam personel: {cnt}")
    print(f"Zeki Göksal: {dict(zeki) if zeki else '❌ bulunamadı'}")
    await conn2.close()

asyncio.run(main())
