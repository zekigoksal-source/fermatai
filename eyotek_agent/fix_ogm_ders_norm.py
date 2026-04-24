"""Normalize OGM Vision ders names — one-off fix."""
import asyncio
import asyncpg
import os
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv
load_dotenv(override=True)


async def main():
    pool = await asyncpg.create_pool(os.getenv('DATABASE_URL'), min_size=1, max_size=2)

    norm_map = {
        'turkce': 'Türkçe', 'türkçe': 'Türkçe', 'TÜRKÇE': 'Türkçe', 'TURKCE': 'Türkçe',
        'türk dili ve edebiyatı': 'Türk Dili ve Edebiyatı',
        'TÜRK DİLİ VE EDEBİYATI': 'Türk Dili ve Edebiyatı',
        'Edebiyat': 'Türk Dili ve Edebiyatı', 'edebiyat': 'Türk Dili ve Edebiyatı',
        'MATEMATİK': 'Matematik', 'MATEMATIK': 'Matematik', 'matematik': 'Matematik',
        'FİZİK': 'Fizik', 'FIZIK': 'Fizik',
        'KİMYA': 'Kimya', 'KIMYA': 'Kimya',
        'BİYOLOJİ': 'Biyoloji', 'BIYOLOJI': 'Biyoloji',
        'COĞRAFYA': 'Coğrafya', 'COGRAFYA': 'Coğrafya', 'Cografya': 'Coğrafya', 'cografya': 'Coğrafya',
        'TARİH': 'Tarih', 'TARIH': 'Tarih',
        'TARİH-1': 'Tarih', 'TARIH-1': 'Tarih',
        'FELSEFE': 'Felsefe',
        'DİN KÜLTÜRÜ': 'Din Kültürü', 'DIN KULTURU': 'Din Kültürü',
    }

    toplam_degisti = 0
    for eski, yeni in norm_map.items():
        if eski == yeni:
            continue
        r = await pool.execute(
            "UPDATE rag_content SET ders = $1 WHERE ders = $2 AND kaynak LIKE '%OGM Vision%'",
            yeni, eski
        )
        try:
            n = int(str(r).split()[-1])
        except Exception:
            n = 0
        if n > 0:
            print(f'  {eski:<30} → {yeni:<22} {n} kayit')
            toplam_degisti += n

    print(f'\nToplam normalize edilen: {toplam_degisti}')

    # Final dağılım
    rows = await pool.fetch(
        "SELECT ders, COUNT(*) FROM rag_content WHERE kaynak LIKE '%OGM Vision%' "
        "GROUP BY ders ORDER BY COUNT(*) DESC"
    )
    print('\n=== FINAL DERS DAĞILIMI ===')
    for r in rows:
        print(f'  {r["ders"]:<25} {r["count"]}')

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
