"""
FermatAI Post-Sync Güncelleme
==============================
Yeni sınav verileri import edildikten sonra çalışır.
Tüm analitik verileri, başarı yüzdelerini ve konu takibini günceller.

Kullanım:
  python post_sync_update.py   # Tüm güncellemeleri çalıştır

Güncellenen:
  1. student_topic_tracker — konu bazlı başarı yüzdeleri (TYT + AYT ayrımı)
  2. student_exam_analysis — birleşik analiz tablosu
  3. analytics_cache — önceden hesaplanmış cache
  4. Trend hesaplama — öğrenci bazlı gelişim
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime

from loguru import logger
from db_pool import get_pool as _get_pool


async def update_topic_tracker():
    """
    Sınav verilerinden konu takibini yeniden hesapla.
    TYT ve AYT sınavlarını AYRI değerlendir.
    """
    pool = await _get_pool()
    conn = await pool.acquire()
    logger.info("Konu takibi güncelleniyor...")

    # Her öğrenci için ders bazlı performans hesapla
    students = await conn.fetch("""
        SELECT DISTINCT soz_no FROM student_exams WHERE soz_no IS NOT NULL
    """)

    updated = 0
    for s in students:
        soz_no = int(s['soz_no'])

        # Son 5 TYT sınavı — ders bazlı net ortalaması
        tyt_exams = await conn.fetch("""
            SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam
            FROM student_exams
            WHERE soz_no = $1 AND exam_code NOT LIKE 'AYT%'
            ORDER BY exam_date DESC NULLS LAST LIMIT 5
        """, soz_no)

        # Son 5 AYT sınavı
        ayt_exams = await conn.fetch("""
            SELECT exam_name, exam_date, turkce, matematik, geometri, fizik, kimya, biyoloji, toplam
            FROM student_exams
            WHERE soz_no = $1 AND exam_code LIKE 'AYT%'
            ORDER BY exam_date DESC NULLS LAST LIMIT 5
        """, soz_no)

        if not tyt_exams and not ayt_exams:
            continue

        # TYT ders bazlı ortalama ve trend
        for ders_adi, kolon, max_net in [
            ("Türkçe", "turkce", 40), ("Matematik", "matematik", 30),
            ("Geometri", "geometri", 10), ("Fizik", "fizik", 7),
            ("Kimya", "kimya", 7), ("Biyoloji", "biyoloji", 6),
        ]:
            nets = [float(e[kolon]) for e in tyt_exams if e[kolon] is not None and e[kolon] > 0]
            if not nets:
                continue

            avg_net = sum(nets) / len(nets)
            basari_pct = round(avg_net / max_net * 100) if max_net > 0 else 0
            basari_pct = min(100, max(0, basari_pct))

            # Trend: son - ilk
            trend = ""
            if len(nets) >= 2:
                diff = nets[0] - nets[-1]  # son - en eski
                if diff > 1:
                    trend = "yukselis"
                elif diff < -1:
                    trend = "dusus"
                else:
                    trend = "stabil"

            # UPSERT
            try:
                await conn.execute("""
                    INSERT INTO student_topic_tracker (soz_no, ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi, status, tamamlandi)
                    VALUES ($1, $2, $3, $4, $5, $6, FALSE)
                    ON CONFLICT (soz_no, ders, konu)
                    DO UPDATE SET sinav_hata_yuzdesi = $4, sinav_hata_sayisi = $5, status = $6
                """, soz_no, f"TYT {ders_adi}", f"Ortalama {avg_net:.1f}/{max_net} net",
                    basari_pct, len(nets), trend or "bekliyor")
                updated += 1
            except Exception:
                # UNIQUE constraint olmayabilir — normal insert dene
                try:
                    existing = await conn.fetchval(
                        "SELECT id FROM student_topic_tracker WHERE soz_no = $1 AND ders = $2 AND konu LIKE 'Ortalama%'",
                        soz_no, f"TYT {ders_adi}")
                    if existing:
                        await conn.execute(
                            "UPDATE student_topic_tracker SET sinav_hata_yuzdesi = $1, sinav_hata_sayisi = $2, status = $3 WHERE id = $4",
                            basari_pct, len(nets), trend or "bekliyor", existing)
                    else:
                        await conn.execute(
                            "INSERT INTO student_topic_tracker (soz_no, ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi, status, tamamlandi) VALUES ($1, $2, $3, $4, $5, $6, FALSE)",
                            soz_no, f"TYT {ders_adi}", f"Ortalama {avg_net:.1f}/{max_net} net",
                            basari_pct, len(nets), trend or "bekliyor")
                    updated += 1
                except Exception as e:
                    logger.debug(f"Topic tracker güncelleme hatası: {e}")

        # AYT ders bazlı (sadece 12+Mezun)
        if ayt_exams:
            for ders_adi, kolon, max_net in [
                ("Fizik", "fizik", 14), ("Kimya", "kimya", 13),
                ("Biyoloji", "biyoloji", 13), ("Matematik", "matematik", 30),
            ]:
                nets = [float(e[kolon]) for e in ayt_exams if e[kolon] is not None and e[kolon] > 0]
                if not nets:
                    continue

                avg_net = sum(nets) / len(nets)
                basari_pct = round(avg_net / max_net * 100) if max_net > 0 else 0
                basari_pct = min(100, max(0, basari_pct))

                try:
                    existing = await conn.fetchval(
                        "SELECT id FROM student_topic_tracker WHERE soz_no = $1 AND ders = $2 AND konu LIKE 'AYT Ort%'",
                        soz_no, f"AYT {ders_adi}")
                    if existing:
                        await conn.execute(
                            "UPDATE student_topic_tracker SET sinav_hata_yuzdesi = $1, sinav_hata_sayisi = $2 WHERE id = $3",
                            basari_pct, len(nets), existing)
                    else:
                        await conn.execute(
                            "INSERT INTO student_topic_tracker (soz_no, ders, konu, sinav_hata_yuzdesi, sinav_hata_sayisi, status, tamamlandi) VALUES ($1, $2, $3, $4, $5, $6, FALSE)",
                            soz_no, f"AYT {ders_adi}", f"AYT Ortalama {avg_net:.1f}/{max_net} net",
                            basari_pct, len(nets), "bekliyor")
                    updated += 1
                except Exception as e:
                    logger.debug(f"AYT topic hatası: {e}")

    await pool.release(conn)
    logger.info(f"Konu takibi güncellendi: {updated} kayıt")
    return updated


async def update_exam_summaries():
    """Öğrenci bazlı sınav özeti güncellemesi — son deneme + trend."""
    pool = await _get_pool()
    conn = await pool.acquire()
    logger.info("Sınav özetleri güncelleniyor...")

    # Her öğrenci için son deneme + trend
    students = await conn.fetch("""
        SELECT DISTINCT soz_no FROM student_exams WHERE toplam IS NOT NULL
    """)

    for s in students:
        soz_no = int(s['soz_no'])

        # Son 3 TYT
        last3 = await conn.fetch("""
            SELECT toplam FROM student_exams
            WHERE soz_no = $1 AND exam_code NOT LIKE 'AYT%' AND toplam IS NOT NULL
            ORDER BY exam_date DESC NULLS LAST LIMIT 3
        """, soz_no)

        if len(last3) >= 2:
            son = float(last3[0]['toplam'])
            onceki = float(last3[1]['toplam'])
            trend = son - onceki
            # Trendi student_exam_analysis'e kaydet (varsa güncelle)
            try:
                await conn.execute("""
                    UPDATE student_exam_analysis
                    SET toplam_net = $1
                    WHERE soz_no::int = $2
                """, son, soz_no)
            except Exception:
                pass

    await pool.release(conn)
    logger.info("Sınav özetleri güncellendi")


async def refresh_cache():
    """Analytics cache'i yenile."""
    try:
        from analytics_cache import get_cached, _cache
        # Cache'i temizle — yeni verilerle yeniden hesaplanacak
        _cache.clear()
        logger.info("Analytics cache temizlendi — sonraki sorguda yeniden hesaplanacak")
    except Exception as e:
        logger.debug(f"Cache temizleme: {e}")


async def generate_sync_report() -> str:
    """Sync sonrası durum raporu."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        tyt = await conn.fetchrow("""
            SELECT COUNT(DISTINCT exam_code) as sinav,
                   COUNT(*) as kayit,
                   MAX(exam_date) as son
            FROM student_exams WHERE exam_code NOT LIKE 'AYT%'
        """)
        ayt = await conn.fetchrow("""
            SELECT COUNT(DISTINCT exam_code) as sinav,
                   COUNT(*) as kayit,
                   MAX(exam_date) as son
            FROM student_exams WHERE exam_code LIKE 'AYT%'
        """)
        topics = await conn.fetchval("SELECT COUNT(*) FROM student_topic_tracker")
        students = await conn.fetchval("SELECT COUNT(DISTINCT soz_no) FROM student_exams")

    return (
        f"📊 *Veri Sync Raporu*\n\n"
        f"---\n\n"
        f"*TYT Sınavları:*\n"
        f"  📝 {tyt['sinav']} farklı sınav, {tyt['kayit']} kayıt\n"
        f"  📅 Son: {tyt['son']}\n\n"
        f"*AYT Sınavları:*\n"
        f"  📝 {ayt['sinav']} farklı sınav, {ayt['kayit']} kayıt\n"
        f"  📅 Son: {ayt['son']}\n\n"
        f"*Konu Takibi:* {topics} kayıt\n"
        f"*Öğrenci:* {students} kişi\n\n"
        f"---\n"
        f"_Tüm değerlendirmeler güncel veriye göre._"
    )


async def main():
    logger.info("Post-sync güncelleme başlatılıyor...")

    # 1. Konu takibi güncelle
    topic_count = await update_topic_tracker()

    # 2. Sınav özetleri güncelle
    await update_exam_summaries()

    # 3. Cache yenile
    await refresh_cache()

    # 4. Rapor
    report = await generate_sync_report()
    print(report)

    logger.info("Post-sync güncelleme tamamlandı!")


if __name__ == "__main__":
    asyncio.run(main())
