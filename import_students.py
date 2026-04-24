"""
Chrome'dan export edilen students_export.json dosyasını PostgreSQL'e import eder.
Çalıştır: python import_students.py
"""
import asyncio, asyncpg, json, os, pathlib, glob
from dotenv import load_dotenv

_here = pathlib.Path(__file__).parent
load_dotenv(_here / "eyotek_agent" / ".env")

# students_export.json'u bul (Downloads veya FermatAI klasöründe)
def find_export_file():
    candidates = [
        _here / "students_export.json",
        pathlib.Path.home() / "Downloads" / "students_export.json",
        pathlib.Path("C:/Users/zekig/Downloads/students_export.json"),
        pathlib.Path("C:/Users/zekig/OneDrive/Desktop/FermatAI/students_export.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("students_export.json bulunamadı! FermatAI klasörüne koyun.")

async def main():
    export_file = find_export_file()
    print(f"📂 Dosya: {export_file}")

    with open(export_file, encoding="utf-8") as f:
        students = json.load(f)
    print(f"📊 {len(students)} öğrenci okundu")

    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))

    # Tabloyu oluştur (yoksa)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            eyotek_id    TEXT PRIMARY KEY,
            soz_no       TEXT,
            full_name    TEXT,
            first_name   TEXT,
            last_name    TEXT,
            sezon        TEXT,
            sube         TEXT,
            class_name   TEXT,
            program      TEXT,
            devre        TEXT,
            kur          TEXT,
            kayit_tarihi TEXT,
            tc_no        TEXT,
            gender       TEXT,
            birth_date   TEXT,
            phone        TEXT,
            parent_name  TEXT,
            status       TEXT,
            last_sync    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    saved = 0
    errors = 0
    for s in students:
        soz_no = s.get("soz_no", "").strip()
        if not soz_no:
            continue

        first_name = s.get("first_name", "").strip()
        last_name  = s.get("last_name", "").strip()
        full_name  = f"{first_name} {last_name}".strip()

        try:
            await conn.execute("""
                INSERT INTO students (
                    eyotek_id, soz_no, full_name, first_name, last_name,
                    sezon, sube, kayit_tarihi, status, last_sync
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, CURRENT_TIMESTAMP)
                ON CONFLICT (eyotek_id) DO UPDATE SET
                    soz_no       = EXCLUDED.soz_no,
                    full_name    = EXCLUDED.full_name,
                    first_name   = EXCLUDED.first_name,
                    last_name    = EXCLUDED.last_name,
                    sezon        = EXCLUDED.sezon,
                    sube         = EXCLUDED.sube,
                    kayit_tarihi = EXCLUDED.kayit_tarihi,
                    status       = EXCLUDED.status,
                    last_sync    = CURRENT_TIMESTAMP
            """,
                soz_no,        # eyotek_id = soz_no (Okul No boş olduğu için)
                soz_no,
                full_name,
                first_name,
                last_name,
                s.get("sezon", ""),
                s.get("sube", ""),
                s.get("kayit_tarihi", ""),
                "Aktif",
            )
            saved += 1
        except Exception as e:
            print(f"  ❌ {soz_no} {full_name}: {e}")
            errors += 1

    await conn.close()

    print(f"\n✅ Tamamlandı: {saved} kayıt, {errors} hata")
    print("\n--- Doğrulama ---")

    # Doğrula
    conn2 = await asyncpg.connect(os.getenv("DATABASE_URL"))
    cnt = await conn2.fetchval("SELECT COUNT(*) FROM students")
    ali = await conn2.fetchrow(
        "SELECT eyotek_id, full_name, soz_no FROM students WHERE full_name ILIKE '%KÜÇÜKUYSAL%' OR soz_no='167'"
    )
    print(f"Toplam öğrenci: {cnt}")
    print(f"Ali Küçükuysal: {dict(ali) if ali else '❌ bulunamadı'}")
    await conn2.close()

asyncio.run(main())
