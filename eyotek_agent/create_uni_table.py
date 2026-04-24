"""Üniversite taban puan tablosu oluştur + temel veri ekle."""
import asyncio, asyncpg, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv; load_dotenv()

async def main():
    conn = await asyncpg.connect(
        (os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL') or (_ for _ in ()).throw(RuntimeError('DATABASE_URL .env de tanimli degil')))
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS universite_taban (
            id SERIAL PRIMARY KEY,
            yil INT NOT NULL,
            universite TEXT NOT NULL,
            bolum TEXT NOT NULL,
            puan_turu TEXT NOT NULL,
            taban_puan NUMERIC,
            siralama INT,
            kontenjan INT,
            sehir TEXT,
            tur TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(yil, universite, bolum, puan_turu)
        )
    """)
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_uni_bolum ON universite_taban(bolum)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_uni_puan ON universite_taban(puan_turu, taban_puan DESC)')

    data = [
        # Tıp SAY
        (2025, 'Hacettepe', 'Tıp', 'SAY', 530.587, 1836, 230, 'Ankara', 'Devlet'),
        (2025, 'İstanbul Üniversitesi-Cerrahpaşa', 'Tıp', 'SAY', 524.068, 3082, 270, 'İstanbul', 'Devlet'),
        (2025, 'Ankara Üniversitesi', 'Tıp', 'SAY', 523.185, 3290, 335, 'Ankara', 'Devlet'),
        (2025, 'İstanbul Üniversitesi', 'Tıp', 'SAY', 518.334, 4532, 285, 'İstanbul', 'Devlet'),
        (2025, 'Gazi Üniversitesi', 'Tıp', 'SAY', 517.636, 4766, 300, 'Ankara', 'Devlet'),
        (2025, 'Ege Üniversitesi', 'Tıp', 'SAY', 516.362, 5118, 320, 'İzmir', 'Devlet'),
        (2025, 'Dokuz Eylül Üniversitesi', 'Tıp', 'SAY', 508.968, 7447, 280, 'İzmir', 'Devlet'),
        (2025, 'Akdeniz Üniversitesi', 'Tıp', 'SAY', 507.483, 7981, 310, 'Antalya', 'Devlet'),
        (2025, 'Çukurova Üniversitesi', 'Tıp', 'SAY', 503.359, 9624, 210, 'Adana', 'Devlet'),
        (2025, 'Bursa Uludağ Üniversitesi', 'Tıp', 'SAY', 502.94, 9803, 230, 'Bursa', 'Devlet'),
        (2025, 'Atatürk Üniversitesi', 'Tıp', 'SAY', 488.978, 16727, 160, 'Erzurum', 'Devlet'),
        (2025, 'Afyonkarahisar Sağlık Bilimleri', 'Tıp', 'SAY', 484.907, 19216, 210, 'Afyon', 'Devlet'),
        # Bilgisayar Mühendisliği SAY (tahmini)
        (2025, 'ODTÜ', 'Bilgisayar Mühendisliği', 'SAY', 520.0, 3800, 120, 'Ankara', 'Devlet'),
        (2025, 'İTÜ', 'Bilgisayar Mühendisliği', 'SAY', 510.0, 6500, 100, 'İstanbul', 'Devlet'),
        (2025, 'Boğaziçi', 'Bilgisayar Mühendisliği', 'SAY', 518.0, 4200, 80, 'İstanbul', 'Devlet'),
        (2025, 'Ege Üniversitesi', 'Bilgisayar Mühendisliği', 'SAY', 470.0, 25000, 80, 'İzmir', 'Devlet'),
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
    print(f'universite_taban: {total} kayit ({inserted} yeni)')
    await conn.close()

asyncio.run(main())
