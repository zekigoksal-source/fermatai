"""
Import etut Excel export into PostgreSQL etut_history table.
Reads the Excel file downloaded from Eyotek Etut Ara page.
"""
import asyncio
import glob
import sys
import openpyxl
import asyncpg
from datetime import datetime

DB_DSN = "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS etut_history (
    id SERIAL PRIMARY KEY,
    sube TEXT,
    etut_kodu INT,
    etut_turu TEXT,
    tarih DATE,
    ogretmen TEXT,
    ders TEXT,
    konu TEXT,
    saat TEXT,
    sure INT,
    derslik TEXT,
    ogrenci_sayisi INT,
    yoklama TEXT,
    kaydeden TEXT,
    olusturma_tarihi TIMESTAMP,
    UNIQUE(etut_kodu)
);
CREATE INDEX IF NOT EXISTS idx_etut_tarih ON etut_history(tarih);
CREATE INDEX IF NOT EXISTS idx_etut_ogretmen ON etut_history(ogretmen);
CREATE INDEX IF NOT EXISTS idx_etut_ders ON etut_history(ders);
"""

# Column mapping: Excel col index (0-based) -> DB column
COL_MAP = {
    0: 'sube',
    1: 'etut_kodu',
    2: 'etut_turu',
    3: 'tarih',
    4: 'ogretmen',
    5: 'ders',
    6: 'konu',
    7: 'saat',
    8: 'sure',
    9: 'derslik',
    10: 'ogrenci_sayisi',
    11: 'yoklama',
    12: 'kaydeden',
    13: 'olusturma_tarihi',
}


def read_excel(filepath):
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = []
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or row[0] is None:
            continue
        record = {}
        for col_idx, db_col in COL_MAP.items():
            val = row[col_idx] if col_idx < len(row) else None
            # Clean up
            if isinstance(val, str):
                val = val.strip()
                if val == 'None' or val == '':
                    val = None
            record[db_col] = val
        # Type conversions
        try:
            record['etut_kodu'] = int(record['etut_kodu']) if record['etut_kodu'] else None
        except (ValueError, TypeError):
            record['etut_kodu'] = None
        try:
            record['sure'] = int(record['sure']) if record['sure'] else None
        except (ValueError, TypeError):
            record['sure'] = None
        try:
            record['ogrenci_sayisi'] = int(record['ogrenci_sayisi']) if record['ogrenci_sayisi'] else None
        except (ValueError, TypeError):
            record['ogrenci_sayisi'] = None
        # Date handling
        if isinstance(record['tarih'], datetime):
            record['tarih'] = record['tarih'].date()
        if isinstance(record['olusturma_tarihi'], str):
            try:
                record['olusturma_tarihi'] = datetime.strptime(record['olusturma_tarihi'], '%Y-%m-%d %H:%M:%S.%f')
            except ValueError:
                record['olusturma_tarihi'] = None
        # Ogretmen name cleanup (double spaces)
        if record['ogretmen']:
            record['ogretmen'] = ' '.join(record['ogretmen'].split())

        if record['etut_kodu']:
            rows.append(record)
    wb.close()
    return rows


async def import_to_db(rows):
    conn = await asyncpg.connect(DB_DSN)
    await conn.execute(CREATE_TABLE)

    # Upsert
    upsert_sql = """
    INSERT INTO etut_history (sube, etut_kodu, etut_turu, tarih, ogretmen, ders, konu, saat, sure, derslik, ogrenci_sayisi, yoklama, kaydeden, olusturma_tarihi)
    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
    ON CONFLICT (etut_kodu) DO UPDATE SET
        sube=EXCLUDED.sube, etut_turu=EXCLUDED.etut_turu, tarih=EXCLUDED.tarih,
        ogretmen=EXCLUDED.ogretmen, ders=EXCLUDED.ders, konu=EXCLUDED.konu,
        saat=EXCLUDED.saat, sure=EXCLUDED.sure, derslik=EXCLUDED.derslik,
        ogrenci_sayisi=EXCLUDED.ogrenci_sayisi, yoklama=EXCLUDED.yoklama,
        kaydeden=EXCLUDED.kaydeden, olusturma_tarihi=EXCLUDED.olusturma_tarihi
    """

    inserted = 0
    errors = 0
    for r in rows:
        try:
            await conn.execute(upsert_sql,
                r['sube'], r['etut_kodu'], r['etut_turu'], r['tarih'],
                r['ogretmen'], r['ders'], r['konu'], r['saat'],
                r['sure'], r['derslik'], r['ogrenci_sayisi'],
                r['yoklama'], r['kaydeden'], r['olusturma_tarihi'])
            inserted += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [!] Row etut_kodu={r.get('etut_kodu')}: {e}")

    # Stats
    total = await conn.fetchval("SELECT COUNT(*) FROM etut_history")
    date_range = await conn.fetchrow("SELECT MIN(tarih), MAX(tarih) FROM etut_history")
    teachers = await conn.fetch("SELECT ogretmen, COUNT(*) as cnt FROM etut_history GROUP BY ogretmen ORDER BY cnt DESC")
    subjects = await conn.fetch("SELECT ders, COUNT(*) as cnt FROM etut_history GROUP BY ders ORDER BY cnt DESC")
    yoklama = await conn.fetch("SELECT yoklama, COUNT(*) as cnt FROM etut_history GROUP BY yoklama ORDER BY cnt DESC")

    await conn.close()

    print(f"\n=== Etut History Import ===")
    print(f"Excel rows: {len(rows)}")
    print(f"Upserted: {inserted}, Errors: {errors}")
    print(f"Total in DB: {total}")
    print(f"Date range: {date_range['min']} -> {date_range['max']}")
    print(f"\nOgretmen dagilimi:")
    for t in teachers:
        print(f"  {t['ogretmen']}: {t['cnt']} etut")
    print(f"\nDers dagilimi:")
    for s in subjects:
        print(f"  {s['ders']}: {s['cnt']} etut")
    print(f"\nYoklama durumu:")
    for y in yoklama:
        print(f"  {y['yoklama']}: {y['cnt']}")


async def main():
    # Find latest Excel file
    files = glob.glob('C:/Users/zekig/Downloads/Et*Ara*.xlsx')
    if not files:
        print("[X] Excel dosyasi bulunamadi!")
        sys.exit(1)
    files.sort(key=lambda f: __import__('os').path.getmtime(f), reverse=True)
    filepath = files[0]
    print(f"Reading: {filepath}")

    rows = read_excel(filepath)
    print(f"Parsed {len(rows)} etut records")

    await import_to_db(rows)


if __name__ == '__main__':
    asyncio.run(main())
