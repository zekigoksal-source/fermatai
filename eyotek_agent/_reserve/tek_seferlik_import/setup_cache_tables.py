"""FermatAI — Cache tablolarını oluştur."""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai")

TABLES = [
    """CREATE TABLE IF NOT EXISTS class_roster (
        id SERIAL PRIMARY KEY, sinif TEXT NOT NULL, devre TEXT,
        soz_no TEXT, okul_no TEXT, ad TEXT, soyad TEXT,
        mudur TEXT, mudur_yardimcisi TEXT, rehber TEXT,
        sinif_ogretmeni TEXT, danisman TEXT,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sinif, soz_no))""",
    "CREATE INDEX IF NOT EXISTS idx_class_roster_sinif ON class_roster(sinif)",
    "CREATE INDEX IF NOT EXISTS idx_class_roster_soz_no ON class_roster(soz_no)",

    """CREATE TABLE IF NOT EXISTS class_timetable (
        id SERIAL PRIMARY KEY, sinif TEXT NOT NULL, gun TEXT NOT NULL,
        saat TEXT NOT NULL, ders TEXT, ogretmen TEXT, derslik TEXT,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sinif, gun, saat))""",
    "CREATE INDEX IF NOT EXISTS idx_class_tt_sinif ON class_timetable(sinif)",

    """CREATE TABLE IF NOT EXISTS teacher_timetable (
        id SERIAL PRIMARY KEY, ogretmen_id TEXT NOT NULL, ogretmen_ad TEXT,
        brans TEXT, haftalik_saat INTEGER, gun TEXT NOT NULL, saat TEXT NOT NULL,
        sinif TEXT, ders TEXT, derslik TEXT,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ogretmen_id, gun, saat))""",
    "CREATE INDEX IF NOT EXISTS idx_teacher_tt_id ON teacher_timetable(ogretmen_id)",

    """CREATE TABLE IF NOT EXISTS etut_reports_cache (
        id SERIAL PRIMARY KEY, ogretmen_id TEXT NOT NULL, sube TEXT,
        tarih_ay TEXT, full_name TEXT, toplam_mesai INTEGER DEFAULT 0,
        toplam_ders INTEGER DEFAULT 0, toplam_etut INTEGER DEFAULT 0,
        ogrenci_sayisi INTEGER DEFAULT 0, basari TEXT,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ogretmen_id, tarih_ay))""",

    """CREATE TABLE IF NOT EXISTS etut_student_control_cache (
        id SERIAL PRIMARY KEY, soz_no TEXT NOT NULL, okul_no TEXT,
        ad TEXT, soyad TEXT, devre TEXT, sinif TEXT,
        yapildi INTEGER DEFAULT 0, gelmedi INTEGER DEFAULT 0,
        kontrol_edilmedi INTEGER DEFAULT 0, toplam INTEGER DEFAULT 0,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(soz_no))""",
    "CREATE INDEX IF NOT EXISTS idx_etut_ctrl_sinif ON etut_student_control_cache(sinif)",

    """CREATE TABLE IF NOT EXISTS carsaf_liste_cache (
        id SERIAL PRIMARY KEY, sube TEXT, gun TEXT NOT NULL,
        sinif TEXT NOT NULL, ders_no INTEGER NOT NULL, saat TEXT,
        ogretmen TEXT, ders TEXT, derslik TEXT,
        last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(gun, sinif, ders_no))""",

    """CREATE TABLE IF NOT EXISTS data_freshness (
        module TEXT PRIMARY KEY, refresh_type TEXT NOT NULL,
        interval_hrs INTEGER DEFAULT 24, description TEXT,
        last_sync TIMESTAMP)""",
]

SEEDS = [
    ("students", "daily", 24, "Ogrenci listesi"),
    ("staff", "weekly", 168, "Personel listesi"),
    ("attendance", "daily", 4, "Yoklama"),
    ("class_roster", "weekly", 168, "Sinif kadrolari"),
    ("class_timetable", "monthly", 336, "Sinif ders programi"),
    ("teacher_timetable", "monthly", 336, "Ogretmen ders programi"),
    ("carsaf_liste", "monthly", 336, "Carsaf liste"),
    ("etut_reports", "daily", 12, "Etut raporlari"),
    ("etut_student_control", "daily", 12, "Ogrenci etut kontrol"),
    ("exams", "weekly", 168, "Sinav katalogu"),
    ("exam_results", "weekly", 168, "Sinav sonuclari"),
]


async def main():
    conn = await asyncpg.connect(DATABASE_URL)
    print("PostgreSQL baglandi.")

    for sql in TABLES:
        await conn.execute(sql)
    print(f"{len(TABLES)} tablo/index olusturuldu.")

    for s in SEEDS:
        await conn.execute(
            "INSERT INTO data_freshness (module, refresh_type, interval_hrs, description) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT (module) DO NOTHING",
            *s,
        )
    print(f"{len(SEEDS)} freshness seed eklendi.")

    # Tablolari listele
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    print(f"\n{'Tablo':<35} {'Kayit':>8}")
    print("-" * 45)
    for t in tables:
        name = t["tablename"]
        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {name}")
        print(f"  {name:<33} {cnt:>8}")

    # Freshness
    rows = await conn.fetch("SELECT * FROM data_freshness ORDER BY module")
    print(f"\n{'Modul':<25} {'Tip':<10} {'Aralik':>8}")
    print("-" * 45)
    for r in rows:
        print(f"  {r['module']:<23} {r['refresh_type']:<10} {r['interval_hrs']:>6}h")

    await conn.close()
    print("\nTamamlandi!")


if __name__ == "__main__":
    asyncio.run(main())
