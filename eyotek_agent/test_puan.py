"""Puan hesaplama doğrulama — DB'deki gerçek ÖSYM puanlarıyla karşılaştır."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()
from puan_hesaplama import hesapla_tyt

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    rows = await conn.fetch("""
        SELECT se.soz_no, s.full_name,
               se.turkce, se.matematik, se.geometri, se.fizik, se.kimya, se.biyoloji, se.toplam,
               sea.ham_puan, sea.yerlesme_puani
        FROM student_exams se
        JOIN students s ON s.soz_no::text = se.soz_no::text
        JOIN student_exam_analysis sea ON sea.soz_no::text = se.soz_no::text
        WHERE sea.ham_puan IS NOT NULL AND sea.ham_puan != ''
          AND se.exam_name NOT LIKE '[AYT]%'
          AND se.exam_date = (
              SELECT MAX(se2.exam_date) FROM student_exams se2
              WHERE se2.soz_no = se.soz_no AND se2.exam_name NOT LIKE '[AYT]%'
          )
        ORDER BY CAST(REPLACE(sea.ham_puan, ',', '.') AS FLOAT) DESC
        LIMIT 15
    """)

    print("ISIM                 GERCEK   HESAP    FARK   | Tr   Mat  Fen  Sos  Top")
    print("-" * 80)
    toplam_fark = 0
    cnt = 0
    for r in rows:
        tr = float(r['turkce'] or 0)
        mat = float(r['matematik'] or 0) + float(r['geometri'] or 0)
        fiz = float(r['fizik'] or 0)
        kim = float(r['kimya'] or 0)
        bio = float(r['biyoloji'] or 0)
        fen = fiz + kim + bio
        toplam = float(r['toplam'] or 0)
        sos = max(0, toplam - tr - mat - fen)

        gercek = float(str(r['ham_puan']).replace(',', '.'))
        hesap = hesapla_tyt(turkce=tr, sosyal=sos, matematik=mat, fen=fen, diploma=80)
        fark = hesap['puan'] - gercek
        toplam_fark += abs(fark)
        cnt += 1
        name = r['full_name'][:20]
        print(f"  {name:20s} {gercek:7.1f} {hesap['puan']:7.1f} {fark:+6.1f}  | {tr:4.1f} {mat:4.1f} {fen:4.1f} {sos:4.1f} {toplam:5.1f}")

    if cnt:
        print(f"\nOrtalama mutlak fark: {toplam_fark/cnt:.1f} puan")
        if toplam_fark/cnt < 20:
            print("Katsayilar MAKUL ✓")
        elif toplam_fark/cnt < 50:
            print("Katsayilar YAKIN — ince ayar gerekebilir")
        else:
            print("Katsayilar UZAK — kalibrasyon lazim!")
    await conn.close()

asyncio.run(main())
