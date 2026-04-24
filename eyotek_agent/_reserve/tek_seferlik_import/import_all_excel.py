"""
Generic Excel importer for Eyotek exports.
Handles: Devamsizlik Sayisi, and future exports.
"""
import asyncio
import glob
import sys
import openpyxl
import asyncpg
from datetime import datetime

DB_DSN = "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai"


async def import_devamsizlik():
    """Import Devamsizlik Sayisi (attendance count per student)."""
    files = glob.glob('C:/Users/zekig/Downloads/Devamsizlik*.xlsx')
    if not files:
        print("[SKIP] Devamsizlik Excel not found")
        return

    import os
    files.sort(key=os.path.getmtime, reverse=True)
    filepath = files[0]
    print(f"Reading devamsizlik: {filepath}")

    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active

    conn = await asyncpg.connect(DB_DSN)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS devamsizlik_sayisi (
        id SERIAL PRIMARY KEY,
        sube TEXT,
        devre TEXT,
        sinif TEXT,
        soz_no INT UNIQUE,
        okul_no TEXT,
        adi TEXT,
        soyadi TEXT,
        toplam_saat INT,
        kayit_silinme_tarihi TEXT,
        last_sync TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_devamsizlik_soz ON devamsizlik_sayisi(soz_no);
    """)

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        soz_no = row[3]
        try:
            soz_no = int(soz_no) if soz_no else None
        except (ValueError, TypeError):
            soz_no = None
        if not soz_no:
            continue

        toplam = row[7]
        try:
            toplam = int(toplam) if toplam else 0
        except (ValueError, TypeError):
            toplam = 0

        adi = str(row[5] or '').strip()
        soyadi = str(row[6] or '').strip()
        kayit_sil = str(row[8] or '').strip()
        if kayit_sil == 'None':
            kayit_sil = None

        rows.append((
            str(row[0] or '').strip(),  # sube
            str(row[1] or '').strip(),  # devre
            str(row[2] or '').strip(),  # sinif
            soz_no,
            str(row[4] or '').strip() or None,  # okul_no
            adi, soyadi, toplam, kayit_sil
        ))

    inserted = 0
    for r in rows:
        try:
            await conn.execute("""
            INSERT INTO devamsizlik_sayisi (sube, devre, sinif, soz_no, okul_no, adi, soyadi, toplam_saat, kayit_silinme_tarihi, last_sync)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW())
            ON CONFLICT (soz_no) DO UPDATE SET
                toplam_saat=EXCLUDED.toplam_saat, sinif=EXCLUDED.sinif, last_sync=NOW()
            """, *r)
            inserted += 1
        except Exception as e:
            print(f"  [!] {r[3]}: {e}")

    total = await conn.fetchval("SELECT COUNT(*) FROM devamsizlik_sayisi")
    top5 = await conn.fetch("SELECT adi, soyadi, toplam_saat FROM devamsizlik_sayisi ORDER BY toplam_saat DESC LIMIT 5")
    avg = await conn.fetchval("SELECT ROUND(AVG(toplam_saat)) FROM devamsizlik_sayisi")

    await conn.close()
    wb.close()

    print(f"\n=== Devamsizlik Sayisi Import ===")
    print(f"Upserted: {inserted}, Total: {total}")
    print(f"Ortalama devamsizlik: {avg} saat")
    print(f"\nEn cok devamsiz:")
    for r in top5:
        print(f"  {r['adi']} {r['soyadi']}: {r['toplam_saat']} saat")

    # Cleanup
    import os
    os.remove(filepath)
    print(f"[OK] Excel silindi: {filepath}")


async def main():
    await import_devamsizlik()


if __name__ == '__main__':
    asyncio.run(main())
