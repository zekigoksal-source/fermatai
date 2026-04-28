"""
FermatAI — Gece Precompute Job (22.1n-neo Fikir 2)
====================================================

Her gece 03:00:
  1. En aktif 50 ogrenci icin build_study_plan_context cache warmup
  2. Finans view'lari refresh (materialized benzeri)
  3. Analytics cache refresh
  4. Schema cache refresh (7 gun birikecek, 1 saat TTL zaten var)

HEDEF: Sabah sorgulari 45s degil, 2s donsun.

Calistir:
  python precompute_nightly.py              # bir defalik
  python precompute_nightly.py --dry         # okuma testi

Zamanlama (bridge lifespan'da):
  asyncio.create_task(nightly_loop())  # 03:00 cron
"""
from __future__ import annotations

import asyncio
import os
import sys
import io
from datetime import datetime, time as dt_time
from loguru import logger

from db_pool import db_fetch


async def precompute_study_plans(limit: int = 50) -> int:
    """Son 30 gunde aktif olmus ogrenciler icin plan context precompute.

    En aktif N ogrenci (mesaj sayisina gore).
    """
    try:
        rows = await db_fetch("""
            SELECT a.phone, COUNT(*) AS msg_count
            FROM agent_conversations a
            WHERE a.role = 'ogrenci'
              AND a.created_at > NOW() - INTERVAL '30 days'
            GROUP BY a.phone
            ORDER BY msg_count DESC
            LIMIT $1
        """, limit)

        count = 0
        from study_plan_builder import build_study_plan_context

        for r in rows:
            phone = r["phone"]
            # Phone → soz_no
            soz = await db_fetch(
                """SELECT s.soz_no::int AS soz_no FROM students s
                   WHERE s.phone = $1 OR s.velicep = $1 OR s.annecep = $1 OR s.babacep = $1
                   LIMIT 1""",
                phone
            )
            if not soz:
                continue
            try:
                result = await build_study_plan_context(soz[0]["soz_no"], force_refresh=True)
                if not result.get("error"):
                    count += 1
            except Exception as e:
                logger.debug(f"precompute plan err {phone}: {e}")
        return count
    except Exception as e:
        logger.error(f"precompute_study_plans hata: {e}")
        return 0


async def refresh_schema_cache():
    """DB schema cache'i sifirla ve yenile."""
    try:
        from db_schema_cache import get_schema_cache
        await get_schema_cache(force_refresh=True)
        return True
    except Exception as e:
        logger.debug(f"schema refresh: {e}")
        return False


async def refresh_analytics_cache():
    """Analytics cache yenile (kurum geneli hesaplamalar)."""
    try:
        from analytics_cache import build_all_caches
        await build_all_caches()
        return True
    except Exception as e:
        logger.debug(f"analytics refresh: {e}")
        return False


async def run_nightly():
    """Gece tum precompute'lari sirayla yap."""
    start = datetime.now()
    logger.info(f"🌙 [NIGHTLY] {start:%H:%M:%S} — Gece precompute basladi")

    report = {"start": start.isoformat(), "steps": {}}

    # 0. Eyotek -> DB sinav sync (Oturum 25.29) — yeni denemeler otomatik gelsin
    #    Diger cache adimlarindan ONCE calisir ki analytics+predicted+followup taze veri gorsun.
    try:
        from sync_recent_exams import sync_recent_exams
        sync_rep = await sync_recent_exams(
            days=30, dry_run=False, trigger="nightly", max_exams_per_run=8
        )
        report["steps"]["sinav_sync"] = (
            f"new={sync_rep.get('exams_new', 0)} "
            f"rows={sync_rep.get('rows_inserted', 0)}"
        )
        report["steps"]["sinav_sync_detail"] = {
            "drilled": sync_rep.get("drilled", []),
            "skipped": sync_rep.get("skipped", []),
        }
        logger.info(
            f"  📥 Sinav sync: {sync_rep.get('exams_new', 0)} yeni sinav, "
            f"{sync_rep.get('rows_inserted', 0)} satir DB'ye yazildi"
        )
        # Yeni sinav ingest edildiyse: SADECE DB log (sync_run_log zaten yazildi).
        # WP bildirim YASAK kurali — Neo manuel "son sync" sorgulayabilir.
        # Optional: Neo flag aktive ederse WP gonderilir.
        if sync_rep.get("rows_inserted", 0) > 0:
            try:
                from db_pool import db_fetchval
                wp_flag = await db_fetchval(
                    "SELECT value FROM sistem_ayar WHERE key='SYNC_NOTIFY_NEO_WP'"
                )
                if (wp_flag or "").lower() == "true":
                    neo_phone = os.getenv("NEO_PHONE") or "905051256802"
                    msg = (
                        f"📥 Sinav sync ozet:\n"
                        f"• {sync_rep['exams_new']} yeni sinav\n"
                        f"• {sync_rep['rows_inserted']} ogrenci-sinav satiri\n"
                        f"Drill: " + ", ".join(
                            d.get("exam_name", "?") for d in sync_rep.get("drilled", [])[:3]
                        )
                    )
                    try:
                        from secure_messenger import send_wp_message
                        await send_wp_message(neo_phone, msg)
                    except Exception as werr:
                        logger.debug(f"  WP notify skip: {werr}")
            except Exception as e:
                logger.debug(f"  notify check skip: {e}")
    except Exception as e:
        report["steps"]["sinav_sync_err"] = str(e)[:200]
        logger.warning(f"  📥 Sinav sync hata: {e}")

    # 0.5 Etut ogrenci kontrol sync (Oturum 25.29 — Neo "Beyza 0 etut" bug)
    #    etut_student_control tablosu Eyotek individual-lesson-control-student'tan
    #    yenilenir. Bu tablo "bireysel ders" ozeti (toplam etut DEGIL).
    try:
        from sync_etut_kontrol import sync_etut_student_control
        ek_rep = await sync_etut_student_control(trigger="nightly")
        if ek_rep.get("error"):
            report["steps"]["etut_kontrol_sync_err"] = ek_rep["error"][:120]
            logger.warning(f"  🎓 Etut kontrol sync hata: {ek_rep['error']}")
        else:
            report["steps"]["etut_kontrol_sync"] = (
                f"fetched={ek_rep.get('fetched', 0)} "
                f"upsert={ek_rep.get('inserted', 0) + ek_rep.get('updated', 0)}"
            )
            logger.info(
                f"  🎓 Etut kontrol: {ek_rep.get('fetched', 0)} kayit fetched, "
                f"{ek_rep.get('inserted', 0) + ek_rep.get('updated', 0)} upsert"
            )
    except Exception as e:
        report["steps"]["etut_kontrol_sync_err"] = str(e)[:200]
        logger.warning(f"  🎓 Etut kontrol sync hata: {e}")

    # 1. Study plan cache warmup
    try:
        n = await precompute_study_plans(limit=50)
        report["steps"]["study_plans"] = n
        logger.info(f"  📚 {n} ogrenci plan context cachelendi")
    except Exception as e:
        report["steps"]["study_plans_err"] = str(e)

    # 2. Schema cache
    ok = await refresh_schema_cache()
    report["steps"]["schema_cache"] = "ok" if ok else "fail"
    logger.info(f"  📊 Schema cache: {report['steps']['schema_cache']}")

    # 3. Analytics cache
    ok = await refresh_analytics_cache()
    report["steps"]["analytics_cache"] = "ok" if ok else "fail"
    logger.info(f"  📈 Analytics cache: {report['steps']['analytics_cache']}")

    # 4. Finans snapshot sync (28 Nisan eklendi — Neo "snapshot 7gun eski" buldu)
    try:
        from finans_eyotek_reader import sync_all_seasons
        # Sadece aktif sezon (2025.26) — diger sezonlar manuel
        finans_report = await sync_all_seasons(
            sezonlar=["2025.26"], dry_run=False, skip_past_students=True
        )
        ok_count = sum(
            1 for s in finans_report.get("sezonlar", {}).values()
            if not s.get("error")
        )
        report["steps"]["finans_snapshot"] = f"ok ({ok_count} sezon)"
        logger.info(f"  💰 Finans snapshot sync: {ok_count} sezon")
    except Exception as e:
        report["steps"]["finans_snapshot_err"] = str(e)[:200]
        logger.warning(f"  💰 Finans snapshot sync hata: {e}")

    # 5. F5 (25.28): Predicted Grade cache yenile — Çalışmam panel için
    try:
        from predicted_grade import refresh_all_predictions
        pg = await refresh_all_predictions(limit=200)
        report["steps"]["predicted_grade"] = f"refreshed {pg['refreshed']}/{pg['total']}"
        logger.info(f"  📊 Predicted Grade: {pg['refreshed']} ogrenci yenilendi")
    except Exception as e:
        report["steps"]["predicted_grade_err"] = str(e)[:200]
        logger.warning(f"  📊 Predicted Grade hata: {e}")

    # 6. F2 (25.28): Auto Follow-Up engine — sınav sync sonrası queue
    try:
        from followup_engine import queue_followups_for_all_active
        fu = await queue_followups_for_all_active(trigger="nightly_exam_check")
        report["steps"]["followup_queue"] = (
            f"queued {fu['queued']}/{fu['checked']} "
            f"(no_weak={fu.get('skipped_no_weak',0)})"
        )
        logger.info(f"  🔁 Follow-Up: {fu['queued']} ogrenci icin queue olustu")
    except Exception as e:
        report["steps"]["followup_queue_err"] = str(e)[:200]
        logger.warning(f"  🔁 Follow-Up hata: {e}")

    # 7. Data Freshness audit (Oturum 25.29) — stale modulleri raporla
    try:
        from data_freshness_helper import list_stale_modules
        stale = await list_stale_modules(threshold_hours=25)
        if stale:
            stale_lines = [
                f"  ⚠️ {m['module']}: {m['yas_saat']:.1f}h eski"
                + (f" (last_error: {m['last_error'][:60]})" if m.get('last_error') else "")
                for m in stale[:10]
            ]
            report["steps"]["stale_modules"] = [m["module"] for m in stale]
            for line in stale_lines:
                logger.warning(line)
        else:
            logger.info("  ✅ Tum modul sync'leri taze (<25h)")
    except Exception as e:
        logger.debug(f"  freshness audit skip: {e}")

    elapsed = (datetime.now() - start).total_seconds()
    report["elapsed_sn"] = round(elapsed, 2)
    logger.info(f"🌙 [NIGHTLY] Tamamlandi ({elapsed:.1f}s)")
    return report


async def nightly_scheduler_loop():
    """Bridge lifespan'de calisan loop — gece 03:00'te run_nightly tetikler."""
    logger.info("🌙 Nightly scheduler loop basladi — her gece 03:00")
    while True:
        try:
            now = datetime.now()
            # Bir sonraki 03:00'e kadar bekle
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target:
                # Yarinki 03:00
                from datetime import timedelta
                target = target + timedelta(days=1)
            wait_sec = (target - now).total_seconds()
            logger.debug(f"  Nightly wait: {wait_sec/3600:.1f} saat sonra tetiklenecek")
            await asyncio.sleep(wait_sec)
            # Tetikle
            await run_nightly()
        except asyncio.CancelledError:
            logger.info("Nightly scheduler iptal edildi")
            break
        except Exception as e:
            logger.error(f"Nightly loop hata: {e}")
            await asyncio.sleep(3600)  # 1 saat sonra tekrar dene


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    import json
    report = asyncio.run(run_nightly())
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
