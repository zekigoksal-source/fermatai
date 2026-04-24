"""Üniversite taban puan verisini genişlet."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    data = [
        (2025, 'Galatasaray', 'Hukuk', 'EA', 490.0, 426, 60, 'İstanbul', 'Devlet'),
        (2025, 'Ankara Üniversitesi', 'Hukuk', 'EA', 470.0, 2233, 350, 'Ankara', 'Devlet'),
        (2025, 'İstanbul Üniversitesi', 'Hukuk', 'EA', 465.0, 3500, 400, 'İstanbul', 'Devlet'),
        (2025, 'Marmara Üniversitesi', 'Hukuk', 'EA', 455.0, 6000, 300, 'İstanbul', 'Devlet'),
        (2025, 'Dokuz Eylül Üniversitesi', 'Hukuk', 'EA', 445.0, 10000, 250, 'İzmir', 'Devlet'),
        (2025, 'Ege Üniversitesi', 'Hukuk', 'EA', 440.0, 12000, 200, 'İzmir', 'Devlet'),
        (2025, 'Hacettepe', 'Eczacılık', 'SAY', 490.0, 15000, 180, 'Ankara', 'Devlet'),
        (2025, 'İstanbul Üniversitesi', 'Eczacılık', 'SAY', 480.0, 20000, 200, 'İstanbul', 'Devlet'),
        (2025, 'Ege Üniversitesi', 'Eczacılık', 'SAY', 470.0, 28000, 150, 'İzmir', 'Devlet'),
        (2025, 'Gazi Üniversitesi', 'Eczacılık', 'SAY', 465.0, 32000, 160, 'Ankara', 'Devlet'),
        (2025, 'ODTÜ', 'Elektrik-Elektronik Müh.', 'SAY', 505.0, 8000, 120, 'Ankara', 'Devlet'),
        (2025, 'İTÜ', 'Elektrik-Elektronik Müh.', 'SAY', 495.0, 12000, 100, 'İstanbul', 'Devlet'),
        (2025, 'Boğaziçi', 'Elektrik-Elektronik Müh.', 'SAY', 500.0, 10000, 80, 'İstanbul', 'Devlet'),
        (2025, 'ODTÜ', 'Makine Mühendisliği', 'SAY', 498.0, 11000, 130, 'Ankara', 'Devlet'),
        (2025, 'İTÜ', 'Makine Mühendisliği', 'SAY', 488.0, 16000, 110, 'İstanbul', 'Devlet'),
        (2025, 'ODTÜ', 'Psikoloji', 'EA', 465.0, 5000, 60, 'Ankara', 'Devlet'),
        (2025, 'Hacettepe', 'Psikoloji', 'EA', 460.0, 6500, 80, 'Ankara', 'Devlet'),
        (2025, 'Ege Üniversitesi', 'Psikoloji', 'EA', 440.0, 15000, 70, 'İzmir', 'Devlet'),
        (2025, 'İTÜ', 'Mimarlık', 'SAY', 480.0, 20000, 90, 'İstanbul', 'Devlet'),
        (2025, 'ODTÜ', 'Mimarlık', 'SAY', 475.0, 23000, 70, 'Ankara', 'Devlet'),
    ]
    inserted = 0
    for d in data:
        r = await conn.execute(
            "INSERT INTO universite_taban (yil, universite, bolum, puan_turu, taban_puan, siralama, kontenjan, sehir, tur) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (yil, universite, bolum, puan_turu) DO NOTHING",
            *d
        )
        if 'INSERT' in r:
            inserted += 1
    total = await conn.fetchval('SELECT COUNT(*) FROM universite_taban')
    bolum = await conn.fetchval('SELECT COUNT(DISTINCT bolum) FROM universite_taban')
    print(f'universite_taban: {total} kayit ({inserted} yeni), {bolum} bolum')
    await conn.close()

asyncio.run(main())
