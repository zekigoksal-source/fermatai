"""
Data Freshness Helper — Oturum 25.29
=====================================

`data_freshness` tablosu icin guvenli sync zamani guncelleme.

ESKI BUG: update_freshness her zaman last_sync=NOW() yaziyordu, success
False olsa bile. Sonuc: bot "attendance taze" saniyordu ama gercek veri
22 gun eski idi.

YENI: success=False'ta last_sync DOKUNULMAZ, sadece last_attempt +
last_error guncellenir. Bot dogru bilgi gorur.

Kullanim:
  from data_freshness_helper import mark_success, mark_failure

  await mark_success("etut_student_control", count=139, notes="cdp_sync")
  await mark_failure("attendance", error="session expired")
"""
from __future__ import annotations
from loguru import logger


async def mark_success(module: str, count: int = 0, notes: str = "") -> None:
    """Sync basarili oldu — last_sync, last_success, last_attempt update."""
    from db_pool import db_execute
    desc = f"{count} kayit | OK | {notes}"[:200]
    try:
        await db_execute(
            """INSERT INTO data_freshness
                 (module, refresh_type, interval_hrs, description,
                  last_sync, last_success, last_attempt, last_error,
                  success_count_24h, fail_count_24h)
               VALUES ($1, 'auto', 4, $2, NOW(), NOW(), NOW(), NULL, 1, 0)
               ON CONFLICT (module) DO UPDATE SET
                 last_sync = NOW(),
                 last_success = NOW(),
                 last_attempt = NOW(),
                 last_error = NULL,
                 description = $2,
                 success_count_24h = data_freshness.success_count_24h + 1""",
            module, desc,
        )
    except Exception as e:
        logger.debug(f"[FRESHNESS] mark_success({module}) fail: {e}")


async def mark_failure(module: str, error: str = "unknown_error", count: int = 0) -> None:
    """Sync basarisiz — last_sync DOKUNMA, last_attempt + last_error update."""
    from db_pool import db_execute
    desc = f"{count} kayit | FAIL | {error[:120]}"[:200]
    try:
        await db_execute(
            """INSERT INTO data_freshness
                 (module, refresh_type, interval_hrs, description,
                  last_attempt, last_error,
                  success_count_24h, fail_count_24h)
               VALUES ($1, 'auto', 4, $2, NOW(), $3, 0, 1)
               ON CONFLICT (module) DO UPDATE SET
                 last_attempt = NOW(),
                 last_error = EXCLUDED.last_error,
                 description = EXCLUDED.description,
                 fail_count_24h = data_freshness.fail_count_24h + 1""",
            module, desc, error[:300],
        )
    except Exception as e:
        logger.debug(f"[FRESHNESS] mark_failure({module}) fail: {e}")


async def get_status(module: str) -> dict:
    """Modül için son durum (rapor için)."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT module, last_sync, last_success, last_attempt, last_error,
                      success_count_24h, fail_count_24h, description
               FROM data_freshness WHERE module=$1""",
            module,
        )
        return dict(row) if row else {}
    except Exception:
        return {}


async def needs_refresh(module: str, max_age_hours: float = 2.0) -> bool:
    """
    25.40p (Neo direktif): Eyotek anlik veri sync gvensizligi cozumu.

    Bot kritik akademik sorulara cevaplamadan once cagrilir:
      - get_student_analytics, get_ayt_analysis, sinav_sonuclari
      - hedef_puan_analiz, puan_tahmin
      - deneme_analiz konuları

    True doonerse: bot eyotek_query/sinav_sonuclari ile anlik fetch + DB update
    yapip sonra cevap vermeli (stale veri ile guvensizlik onlenir).

    Args:
      module: 'students', 'student_exams', 'attendance', 'etut_history' vb.
      max_age_hours: bu yas asilirsa True (default 2 saat — Neo: 'kritik soru icin')
    """
    from db_pool import db_fetchval
    try:
        last_success = await db_fetchval(
            "SELECT last_success FROM data_freshness WHERE module=$1",
            module,
        )
        if not last_success:
            return True  # Hic sync olmadi → refresh
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc) if last_success.tzinfo else datetime.now()
        age_hours = (now - last_success).total_seconds() / 3600.0
        return age_hours > max_age_hours
    except Exception as e:
        logger.debug(f"[FRESHNESS] needs_refresh fail ({module}): {e}")
        return False  # DB hatasi olursa stale degil say (akisi bozma)


async def list_stale_modules(threshold_hours: float = 25) -> list[dict]:
    """N saatten eski sync'leri listele (admin alarm için)."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT module, last_success, last_error,
                      EXTRACT(EPOCH FROM (NOW() - last_success)) / 3600.0 AS yas_saat,
                      fail_count_24h
               FROM data_freshness
               WHERE last_success IS NULL
                  OR last_success < NOW() - ($1 || ' hours')::interval
               ORDER BY last_success NULLS FIRST""",
            str(threshold_hours),
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[FRESHNESS] list_stale fail: {e}")
        return []
