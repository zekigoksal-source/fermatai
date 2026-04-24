"""
Import Rehberlik Notu Excel export into PostgreSQL counsellor_notes table.
"""
import asyncio
import glob
import sys
import openpyxl
import asyncpg
from datetime import datetime

DB_DSN = "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS counsellor_notes (
    id SERIAL PRIMARY KEY,
    sube TEXT,
    ogretmen TEXT,
    devre TEXT,
    sinif TEXT,
    soz_no INT,
    ogrenci_adi TEXT,
    ogrenci_soyadi TEXT,
    gorusme_tarihi TIMESTAMP,
    not_turu TEXT,
    gorusulen TEXT,
    gorusme_turu TEXT,
    not_metni TEXT,
    UNIQUE(soz_no, gorusme_tarihi, ogretmen)
);
CREATE INDEX IF NOT EXISTS idx_cn_soz_no ON counsellor_notes(soz_no);
CREATE INDEX IF NOT EXISTS idx_cn_tarih ON counsellor_notes(gorusme_tarihi);
CREATE INDEX IF NOT EXISTS idx_cn_ogretmen ON counsellor_notes(ogretmen);
"""


def read_excel(filepath):
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        ogretmen = str(row[1] or '').strip()
        if ogretmen:
            ogretmen = ' '.join(ogretmen.split())  # double space fix

        soz_no = row[4]
        try:
            soz_no = int(soz_no) if soz_no else None
        except (ValueError, TypeError):
            soz_no = None

        gorusme_tarihi = row[7]
        if isinstance(gorusme_tarihi, str):
            try:
                gorusme_tarihi = datetime.strptime(gorusme_tarihi, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                gorusme_tarihi = None

        record = {
            'sube': str(row[0] or '').strip() or None,
            'ogretmen': ogretmen or None,
            'devre': str(row[2] or '').strip() or None,
            'sinif': str(row[3] or '').strip() or None,
            'soz_no': soz_no,
            'ogrenci_adi': str(row[5] or '').strip() or None,
            'ogrenci_soyadi': str(row[6] or '').strip() or None,
            'gorusme_tarihi': gorusme_tarihi,
            'not_turu': str(row[8] or '').strip() or None,
            'gorusulen': str(row[9] or '').strip() or None,
            'gorusme_turu': str(row[10] or '').strip() or None,
            'not_metni': str(row[11] or '').strip() or None,
        }
        if record['soz_no'] and record['gorusme_tarihi']:
            rows.append(record)
    wb.close()
    return rows


async def import_to_db(rows):
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute(CREATE_TABLE)

    upsert_sql = """
    INSERT INTO counsellor_notes (sube, ogretmen, devre, sinif, soz_no, ogrenci_adi, ogrenci_soyadi,
        gorusme_tarihi, not_turu, gorusulen, gorusme_turu, not_metni)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
    ON CONFLICT (soz_no, gorusme_tarihi, ogretmen) DO UPDATE SET
        sube=EXCLUDED.sube, devre=EXCLUDED.devre, sinif=EXCLUDED.sinif,
        ogrenci_adi=EXCLUDED.ogrenci_adi, ogrenci_soyadi=EXCLUDED.ogrenci_soyadi,
        not_turu=EXCLUDED.not_turu, gorusulen=EXCLUDED.gorusulen,
        gorusme_turu=EXCLUDED.gorusme_turu, not_metni=EXCLUDED.not_metni
    """

    inserted = 0
    errors = 0
    for r in rows:
        try:
            await conn.execute(upsert_sql,
                r['sube'], r['ogretmen'], r['devre'], r['sinif'], r['soz_no'],
                r['ogrenci_adi'], r['ogrenci_soyadi'], r['gorusme_tarihi'],
                r['not_turu'], r['gorusulen'], r['gorusme_turu'], r['not_metni'])
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  [!] soz_no={r.get('soz_no')}: {e}")

    # Stats
    total = await conn.fetchval("SELECT COUNT(*) FROM counsellor_notes")
    date_range = await conn.fetchrow("SELECT MIN(gorusme_tarihi), MAX(gorusme_tarihi) FROM counsellor_notes")
    by_teacher = await conn.fetch("SELECT ogretmen, COUNT(*) as cnt FROM counsellor_notes GROUP BY ogretmen ORDER BY cnt DESC")
    by_type = await conn.fetch("SELECT not_turu, COUNT(*) as cnt FROM counsellor_notes GROUP BY not_turu ORDER BY cnt DESC")
    by_student = await conn.fetchval("SELECT COUNT(DISTINCT soz_no) FROM counsellor_notes")

    await conn.close()

    print(f"\n=== Counsellor Notes Import ===")
    print(f"Excel rows: {len(rows)}")
    print(f"Upserted: {inserted}, Errors: {errors}")
    print(f"Total in DB: {total}")
    print(f"Date range: {date_range['min']} -> {date_range['max']}")
    print(f"Unique students: {by_student}")
    print(f"\nOgretmen dagilimi:")
    for t in by_teacher:
        print(f"  {t['ogretmen']}: {t['cnt']} not")
    print(f"\nNot turu dagilimi:")
    for t in by_type:
        print(f"  {t['not_turu']}: {t['cnt']}")


async def main():
    files = glob.glob('C:/Users/zekig/Downloads/RehberlikNot*.xlsx')
    if not files:
        print("[X] Excel dosyasi bulunamadi!")
        sys.exit(1)
    files.sort(key=lambda f: __import__('os').path.getmtime(f), reverse=True)
    filepath = files[0]
    print(f"Reading: {filepath}")

    rows = read_excel(filepath)
    print(f"Parsed {len(rows)} counsellor note records")

    await import_to_db(rows)


if __name__ == '__main__':
    asyncio.run(main())
