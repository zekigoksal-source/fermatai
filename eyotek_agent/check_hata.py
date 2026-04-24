"""sinav_hata_yuzdesi gercekte ne? DB'den kontrol."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    # Göktürk Han — topic tracker
    rows = await conn.fetch("""
        SELECT ders, konu, sinav_hata_sayisi, sinav_hata_yuzdesi, status
        FROM student_topic_tracker
        WHERE soz_no = (SELECT soz_no::int FROM students WHERE full_name ILIKE '%GÖKTÜRK%' LIMIT 1)
        ORDER BY CAST(sinav_hata_yuzdesi AS NUMERIC) DESC
        LIMIT 10
    """)
    print("GÖKTÜRK HAN — student_topic_tracker:")
    print(f"{'DERS':12s} {'KONU':30s} {'HATA_SAYI':>10s} {'HATA_%':>8s}")
    print("-" * 65)
    for r in rows:
        print(f"{r['ders']:12s} {r['konu']:30s} {str(r['sinav_hata_sayisi']):>10s} {str(r['sinav_hata_yuzdesi']):>8s}")

    # Ayrica oncelikli_konular JSON kontrol
    sea = await conn.fetchrow("""
        SELECT oncelikli_konular FROM student_exam_analysis
        WHERE soz_no = (SELECT soz_no::text FROM students WHERE full_name ILIKE '%GÖKTÜRK%' LIMIT 1)
    """)
    if sea and sea['oncelikli_konular']:
        print(f"\noncelikli_konular: {str(sea['oncelikli_konular'])[:500]}")

    # Basit kontrol: en yüksek hata_yuzdesi olanlar gerçekten zayıf mı?
    print("\n=== MANTIK KONTROLÜ ===")
    print("Eğer sinav_hata_yuzdesi = HATA ise:")
    print("  Yüksek yüzde = ÇOK HATA = ZAYIF konu")
    print("  Düşük yüzde = AZ HATA = GÜÇLÜ konu")
    print()
    print("Eğer sinav_hata_yuzdesi = BAŞARI ise:")
    print("  Yüksek yüzde = ÇOK BAŞARI = GÜÇLÜ konu")
    print("  Düşük yüzde = AZ BAŞARI = ZAYIF konu")
    print()

    # En düşük yüzdeli konular
    low = await conn.fetch("""
        SELECT ders, konu, sinav_hata_sayisi, sinav_hata_yuzdesi
        FROM student_topic_tracker
        WHERE soz_no = (SELECT soz_no FROM students WHERE full_name ILIKE '%GÖKTÜRK%' LIMIT 1)
        ORDER BY sinav_hata_yuzdesi ASC
        LIMIT 5
    """)
    print("EN DÜŞÜK YÜZDE (bunlar zayıf mı güçlü mü?):")
    for r in low:
        print(f"  {r['ders']:12s} {r['konu']:30s} hata_sayi={r['sinav_hata_sayisi']:>5s} yuzde={r['sinav_hata_yuzdesi']:>6s}")

    await conn.close()

asyncio.run(main())
