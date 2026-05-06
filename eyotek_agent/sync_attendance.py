"""
FermatAI — Yoklama Sync (Cache-First, Scheduled)
=================================================
Eyotek'ten yoklama_kontrol verisini periyodik çeker.
Bot koruması için günde 4 sync (09/13/19/23:30).

Kullanım:
  python sync_attendance.py             # son 1 gün
  python sync_attendance.py --days 7    # son 7 gün
  python sync_attendance.py --full      # tüm sezon
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)
sys.path.insert(0, str(Path(__file__).parent))

from db_pool import get_pool as _get_pool, db_fetchrow, db_execute


async def ensure_data_freshness_table():
    """data_freshness tablosu — her sync türünün son zamanını izler."""
    # Tablo zaten var (module, refresh_type, interval_hrs, description, last_sync)
    # Noop — pool lazy init eder
    pass


async def get_last_sync(module: str) -> dict | None:
    row = await db_fetchrow(
        "SELECT last_sync, refresh_type, description FROM data_freshness WHERE module=$1",
        module,
    )
    return row if row else None


async def update_freshness(module: str, count: int, success: bool, notes: str = ""):
    """data_freshness guncelleme — Oturum 25.29 fix.

    ESKI BUG: success=False oldugunda bile last_sync=NOW() yaziliyordu →
    bot "attendance taze" saniyordu, oysa veri 22 gun eski idi.

    YENI MANTIK:
      - last_attempt: HER ZAMAN NOW() (en son deneme)
      - last_success: SADECE success=True'da NOW() (en son basarili sync)
      - last_sync: GERIYE UYUMLULUK — success'taki NOW(), fail'da DOKUNMA
      - last_error: success=False ise notes, True ise NULL
    """
    desc = f"{count} kayit | {'OK' if success else 'FAIL'} | {notes}"[:200]
    if success:
        await db_execute(
            """INSERT INTO data_freshness
                 (module, refresh_type, interval_hrs, description,
                  last_sync, last_success, last_attempt, last_error)
               VALUES ($1, 'auto', 4, $2, NOW(), NOW(), NOW(), NULL)
               ON CONFLICT (module) DO UPDATE SET
                 last_sync = NOW(),
                 last_success = NOW(),
                 last_attempt = NOW(),
                 last_error = NULL,
                 description = $2,
                 success_count_24h = data_freshness.success_count_24h + 1""",
            module, desc,
        )
    else:
        # FAIL durumu: last_sync ve last_success'i KORU, sadece attempt + error guncelle
        await db_execute(
            """INSERT INTO data_freshness
                 (module, refresh_type, interval_hrs, description,
                  last_attempt, last_error)
               VALUES ($1, 'auto', 4, $2, NOW(), $3)
               ON CONFLICT (module) DO UPDATE SET
                 last_attempt = NOW(),
                 last_error = EXCLUDED.last_error,
                 description = EXCLUDED.description,
                 fail_count_24h = data_freshness.fail_count_24h + 1""",
            module, desc, notes[:300] if notes else "unknown_error",
        )


async def upsert_attendance(records: list[dict]) -> int:
    """yoklama_kontrol tablosuna UPSERT — duplicate kontrol."""
    if not records:
        return 0
    pool = await _get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        for r in records:
            try:
                tarih_str = r.get('tarih', '').strip()
                if not tarih_str:
                    continue
                # Tarih formatı: "06.09.2025" → date
                try:
                    tarih_obj = datetime.strptime(tarih_str, "%d.%m.%Y").date()
                except ValueError:
                    continue
                sinif = (r.get('sinif') or '').strip()
                ders = (r.get('ders') or '').strip()
                yoklama = (r.get('yoklama') or '').strip()
                if not (sinif and ders):
                    continue
                # Mevcut kontrolü — ayni gun/sinif/ders kombinasyonu varsa update
                existing = await conn.fetchrow(
                    "SELECT id, yoklama FROM yoklama_kontrol WHERE tarih=$1 AND sinif=$2 AND ders=$3 AND ders_baslangic=$4 LIMIT 1",
                    tarih_obj, sinif, ders, (r.get('ders_baslangic') or '').strip()
                )
                if existing:
                    if existing['yoklama'] != yoklama:
                        await conn.execute(
                            "UPDATE yoklama_kontrol SET yoklama=$1 WHERE id=$2",
                            yoklama, existing['id']
                        )
                        inserted += 1
                else:
                    await conn.execute(
                        """INSERT INTO yoklama_kontrol
                           (gun, tarih, sinif, ders, ogretmen, ders_baslangic, ders_bitis, yoklama)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        (r.get('gun') or '').strip(),
                        tarih_obj,
                        sinif, ders,
                        (r.get('ogretmen') or '').strip(),
                        (r.get('ders_baslangic') or '').strip(),
                        (r.get('ders_bitis') or '').strip(),
                        yoklama,
                    )
                    inserted += 1
            except Exception as e:
                logger.warning(f"  UPSERT hatasi: {e} | row: {r}")
    return inserted


async def run_attendance_sync(days: int = 1) -> dict:
    """Yoklama sync ana fonksiyon — Eyotek'ten çek, DB'ye yaz."""
    from session_keeper import get_eyotek_status

    status = get_eyotek_status() if 'session_keeper' in sys.modules else {}
    if status.get('eyotek_session') == 'OFFLINE':
        logger.warning("Eyotek session OFFLINE — sync iptal")
        await update_freshness('attendance', 0, False, 'session offline')
        return {'success': False, 'count': 0, 'reason': 'session offline'}

    try:
        # 25.41 (Neo bug 7 May): VPS'te CDP yok + systemd interactive input desteklemez
        # → eyotek_browser_helper._read_session_file() non-interactive yol
        from eyotek_wrapper import EyotekWrapper, session_is_valid
        from eyotek_browser_helper import _read_session_file

        cookies = await _read_session_file()
        if not cookies or not await session_is_valid(cookies):
            # Cookie eksik/expire → auto login dene
            logger.info("[ATTENDANCE] Cookie eksik/expire, auto login")
            try:
                from eyotek_auto_login import try_auto_login
                result = await try_auto_login()
                if result.get("success"):
                    cookies = await _read_session_file()
                else:
                    await update_freshness('attendance', 0, False, f'auto_login fail: {result.get("message", "?")}')
                    return {'success': False, 'count': 0, 'reason': 'auto_login fail'}
            except Exception as e:
                await update_freshness('attendance', 0, False, f'login exc: {str(e)[:100]}')
                return {'success': False, 'count': 0, 'reason': str(e)}

        if not cookies:
            await update_freshness('attendance', 0, False, 'no session after auto_login')
            return {'success': False, 'count': 0, 'reason': 'no session'}

        async with EyotekWrapper(cookies) as ew:
            records = await ew.scrape_attendance_control(days_back=days)

        count = await upsert_attendance(records)
        await update_freshness('attendance', count, True, f'{days} gun')
        logger.success(f"✅ Yoklama sync: {count} yeni/guncel kayit ({days} gun)")
        return {'success': True, 'count': count}
    except Exception as e:
        logger.error(f"Yoklama sync hata: {e}")
        await update_freshness('attendance', 0, False, str(e)[:200])
        return {'success': False, 'count': 0, 'reason': str(e)}


async def main():
    await ensure_data_freshness_table()
    days = 1
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--full" in sys.argv:
        days = 0  # Tum sezon
    result = await run_attendance_sync(days=days)
    print(f"\nSonuc: {result}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
