"""
Sinav verisinden ogrenci konu takip listesi olustur.
student_exam_analysis.oncelikli_konular (JSONB) → student_topic_tracker
"""
import asyncio
import asyncpg

DB_URL = "postgresql://fermat:Ze-zzg10@localhost:5432/fermatai"


async def main():
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT soz_no::int as soz_no, full_name, oncelikli_konular
        FROM student_exam_analysis
        WHERE oncelikli_konular IS NOT NULL
    """)

    total_inserted = 0
    for r in rows:
        soz_no = r['soz_no']
        raw = r['oncelikli_konular']
        # JSONB string olarak kaydedilmis olabilir
        import json
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                continue
        else:
            data = raw

        if not isinstance(data, list):
            continue

        for level_group in data:
            if not isinstance(level_group, dict):
                continue
            konular = level_group.get('konular', [])
            for k in konular:
                if not isinstance(k, dict):
                    continue
                konu_raw = k.get('konu', '')
                if not konu_raw:
                    continue

                # Parse "TYT_Matematik : Denklemler ve ..." → ders=Matematik, konu=Denklemler...
                parts = konu_raw.split(':', 1)
                if len(parts) == 2:
                    ders = parts[0].strip().replace('TYT_', '').replace('AYT_', '')
                    konu = parts[1].strip()
                else:
                    ders = 'Genel'
                    konu = konu_raw.strip()

                yanlis = int(k.get('yanlis', 0) or 0)
                bos = int(k.get('bos', 0) or 0)
                hata = yanlis + bos
                soru = int(k.get('soru', 0) or k.get('soru_sayisi', 0) or 0)

                # Hata yuzdesi hesapla
                yuzde_raw = k.get('yuzde', '')
                if yuzde_raw:
                    try:
                        yuzde = float(str(yuzde_raw).replace('%', '').replace(',', '.'))
                    except (ValueError, TypeError):
                        yuzde = (hata / soru * 100) if soru > 0 else 0
                else:
                    yuzde = (hata / soru * 100) if soru > 0 else 0

                try:
                    await conn.execute("""
                        INSERT INTO student_topic_tracker (soz_no, ders, konu, status, sinav_hata_sayisi, sinav_hata_yuzdesi)
                        VALUES ($1, $2, $3, 'onerilen', $4, $5)
                        ON CONFLICT (soz_no, ders, konu) DO UPDATE SET
                            sinav_hata_sayisi = EXCLUDED.sinav_hata_sayisi,
                            sinav_hata_yuzdesi = EXCLUDED.sinav_hata_yuzdesi
                    """, soz_no, ders, konu, hata, yuzde)
                    total_inserted += 1
                except Exception as e:
                    pass

    # Stats
    total = await conn.fetchval("SELECT COUNT(*) FROM student_topic_tracker")
    students = await conn.fetchval("SELECT COUNT(DISTINCT soz_no) FROM student_topic_tracker")
    top_topics = await conn.fetch("""
        SELECT ders, konu, COUNT(DISTINCT soz_no) as ogrenci_sayisi,
               ROUND(AVG(sinav_hata_yuzdesi)::numeric, 1) as ort_hata
        FROM student_topic_tracker
        GROUP BY ders, konu ORDER BY ogrenci_sayisi DESC LIMIT 10
    """)

    await conn.close()

    print(f"=== Topic Tracker ===")
    print(f"Toplam: {total} konu, {students} ogrenci")
    print(f"Inserted/updated: {total_inserted}")
    print(f"\nEn yaygin zayif konular (kac ogrenci bu konuda zayif):")
    for t in top_topics:
        print(f"  {t['ders']:15s} | {t['konu'][:45]:45s} | {t['ogrenci_sayisi']} ogrenci | ort hata: %{t['ort_hata']}")


if __name__ == '__main__':
    asyncio.run(main())
