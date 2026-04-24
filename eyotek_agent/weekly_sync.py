"""
FermatAI Haftalik Otomatik Sync
================================
Her Cuma aksami yeni deneme verilerini kontrol eder ve DB'yi gunceller.
Ayrica fast_response sablonlarini ve cache'i yeniler.

Kullanim:
  python weekly_sync.py   # Manuel calistir
  BASLAT.bat icinde zamanlanmis gorev olarak calisir
"""

import asyncio
import os
import sys
from datetime import date, datetime

from loguru import logger
from db_pool import get_pool as _get_pool


async def check_new_exams() -> dict:
    """Yeni deneme var mi kontrol et — son sync'ten sonra eklenenler."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # Son deneme tarihi
        last_tyt = await conn.fetchval(
            "SELECT MAX(exam_date) FROM student_exams WHERE exam_code NOT LIKE 'AYT%'")
        last_ayt = await conn.fetchval(
            "SELECT MAX(exam_date) FROM student_exams WHERE exam_code LIKE 'AYT%'")

        # Son 7 gundeki yeni sinavlar
        new_tyt = await conn.fetchval("""
            SELECT COUNT(DISTINCT exam_code) FROM student_exams
            WHERE exam_code NOT LIKE 'AYT%' AND exam_date >= CURRENT_DATE - 7
        """)
        new_ayt = await conn.fetchval("""
            SELECT COUNT(DISTINCT exam_code) FROM student_exams
            WHERE exam_code LIKE 'AYT%' AND exam_date >= CURRENT_DATE - 7
        """)

        # Toplam ogrenci sinav kaydi
        total = await conn.fetchval("SELECT COUNT(*) FROM student_exams")

    return {
        "last_tyt": str(last_tyt) if last_tyt else "yok",
        "last_ayt": str(last_ayt) if last_ayt else "yok",
        "new_tyt_7d": new_tyt or 0,
        "new_ayt_7d": new_ayt or 0,
        "total_records": total or 0,
    }


async def refresh_analytics_cache():
    """Analytics cache'i yenile — yeni verilerle."""
    try:
        from analytics_cache import refresh_all_cache
        await refresh_all_cache()
        logger.info("Analytics cache yenilendi")
    except Exception as e:
        logger.warning(f"Cache yenileme hatasi: {e}")


async def main():
    logger.info("Haftalik sync kontrolu baslatiliyor...")

    # 1. Yeni sinav kontrolu
    status = await check_new_exams()
    logger.info(f"Son TYT: {status['last_tyt']}, Son AYT: {status['last_ayt']}")
    logger.info(f"Son 7 gun: {status['new_tyt_7d']} yeni TYT, {status['new_ayt_7d']} yeni AYT")
    logger.info(f"Toplam: {status['total_records']} sinav kaydi")

    # 2. Eyotek sync gerekiyor mu?
    if status['new_tyt_7d'] == 0:
        logger.info("Yeni sinav yok — Eyotek sync oneriliyor")
        logger.info("Calistir: python sync_exams.py")
    else:
        logger.info(f"Son 7 gunde {status['new_tyt_7d']} yeni TYT sinavi zaten var")

    # 3. Cache yenile
    await refresh_analytics_cache()

    # 4. Rapor
    print(f"\n{'='*50}")
    print(f"HAFTALIK SYNC RAPORU — {date.today().strftime('%d.%m.%Y')}")
    print(f"{'='*50}")
    print(f"Son TYT: {status['last_tyt']}")
    print(f"Son AYT: {status['last_ayt']}")
    print(f"Son 7 gun yeni TYT: {status['new_tyt_7d']}")
    print(f"Son 7 gun yeni AYT: {status['new_ayt_7d']}")
    print(f"Toplam kayit: {status['total_records']}")


if __name__ == "__main__":
    asyncio.run(main())
