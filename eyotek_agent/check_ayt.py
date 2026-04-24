"""AYT veri durumu kontrol — etkilenen öğrenciler."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    # Tüm öğrencilerin AYT durumu
    rows = await conn.fetch("""
        SELECT s.full_name, s.class_name, s.soz_no,
               sea.ham_puan_ayt, sea.yerlesme_puani_ayt,
               sea.sinav_sayisi_ayt, sea.katilan_sinav_ayt
        FROM students s
        LEFT JOIN student_exam_analysis sea ON sea.soz_no::text = s.soz_no::text
        WHERE s.class_name LIKE '%12%' OR s.class_name LIKE '%Mez%' OR s.class_name LIKE '%EA%'
        ORDER BY s.full_name
    """)
    ayt_var = 0
    ayt_yok = 0
    print(f"{'İSİM':25s} {'SINIF':12s} {'AYT':5s} HAM       YERLESME   KATILIM")
    print("-" * 85)
    for r in rows:
        has = "✅" if r['ham_puan_ayt'] else "❌"
        if r['ham_puan_ayt']:
            ayt_var += 1
        else:
            ayt_yok += 1
        ham = r['ham_puan_ayt'] or '-'
        yer = r['yerlesme_puani_ayt'] or '-'
        kat = f"{r['katilan_sinav_ayt'] or '-'}/{r['sinav_sayisi_ayt'] or '-'}"
        print(f"{r['full_name']:25s} {r['class_name']:12s} {has}  {str(ham):10s} {str(yer):10s} {kat}")
    print(f"\nToplam: {ayt_var} AYT var, {ayt_yok} AYT yok ({len(rows)} ogrenci)")

    # Ecrin, Büşra, Nazlı spesifik kontrol
    print("\n=== SORUNLU ÖĞRENCİLER ===")
    for name in ['Ecrin', 'Nazli', 'Busra', 'Ege']:
        r = await conn.fetchrow(
            "SELECT s.full_name, s.soz_no, sea.ham_puan_ayt FROM students s "
            "LEFT JOIN student_exam_analysis sea ON sea.soz_no::text=s.soz_no::text "
            "WHERE s.full_name ILIKE $1 LIMIT 1",
            f'%{name}%'
        )
        if r:
            status = f"AYT VAR ({r['ham_puan_ayt']})" if r['ham_puan_ayt'] else "AYT YOK"
            print(f"  {r['full_name']}: soz_no={r['soz_no']} → {status}")
    await conn.close()

asyncio.run(main())
