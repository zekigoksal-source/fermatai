"""
FermatAI WhatsApp Bridge
========================
Meta WhatsApp Business API webhook alıcısı → FermatCoreAgent köprüsü.

Akış:
  WhatsApp mesajı (metin / ses / görüntü)
    → Meta Webhook (POST /webhook)
    → ACL: telefon rolü kontrol
    → IntentParser: niyet çıkar (ses → Whisper önce)
    → FermatCoreAgent: tool-calling + pedagojik muhakeme
    → WhatsApp API: yanıt gönder

Çalıştırma:
  uvicorn whatsapp_bridge:app --host 0.0.0.0 --port 8001 --reload

n8n entegrasyonu:
  n8n'de "Webhook" node → bu servisin /webhook endpoint'ini çağırır
  VEYA Meta'yı doğrudan bu endpoint'e yönlendir (Webhook URL ayarı)

Ortam değişkenleri (.env):
  WA_VERIFY_TOKEN     → Meta webhook doğrulama token'ı
  WA_ACCESS_TOKEN     → WhatsApp Business API access token
  WA_PHONE_NUMBER_ID  → Meta'dan alınan Phone Number ID
  ANTHROPIC_API_KEY   → Claude API anahtarı
  DATABASE_URL        → PostgreSQL bağlantı URL'i
"""

import asyncio
import hashlib
import hmac
import json
import os
from wa_config import GRAPH_BASE  # 25.50 Graph API tek-kaynak (wa_config.py)
import re
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from loguru import logger

load_dotenv(override=True)

# ── LOG ROTATION (Oturum 18) ─────────────────────────────────────────────────
# Loguru file sink: otomatik rotation, 14 gun retention, zip compress
# Bridge stdout/stderr uvicorn redirect'te kalir — bu sink yapilandirilmis log icin
try:
    from pathlib import Path as _LogPath
    _log_dir = _LogPath(__file__).parent / "logs"
    _log_dir.mkdir(exist_ok=True)
    logger.add(
        str(_log_dir / "bridge_{time:YYYY-MM-DD}.log"),
        rotation="20 MB",       # 20MB'a ulasinca yeni dosya
        retention="14 days",    # 14 gun sonra sil
        compression="zip",      # Eski dosyalari sikistir
        level="INFO",
        enqueue=True,           # Thread-safe
    )
except Exception:
    pass  # Log rotation kurulmazsa bridge devam etsin

# ── Config ────────────────────────────────────────────────────────────────────
WA_VERIFY_TOKEN    = os.getenv("WA_VERIFY_TOKEN", "fermatai_verify_2026")
WA_ACCESS_TOKEN    = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_APP_SECRET      = os.getenv("WA_APP_SECRET", "")   # webhook imza doğrulama
WA_API_URL         = f"{GRAPH_BASE}/{WA_PHONE_NUMBER_ID}/messages"

# ── 22.1n-kural1: OUTREACH GUARD (Neo KRITIK, 20 Nisan) ─────────────────────
# Proaktif mesaj (kullanicidan gelen cevap DEGIL) Neo onayi olmadan GITMEZ.
# Default: OUTREACH_ENABLED=false. Yeni sezonda (1 Eylul 2026) Neo True yapacak.
# Bloklanan mesajlar outreach_pending tablosuna dusululur (Neo toplu onay yapabilir).
OUTREACH_ENABLED = os.getenv("OUTREACH_ENABLED", "false").lower() in ("1", "true", "yes")
ADMIN_PHONE_ENV  = (os.getenv("ADMIN_PHONE", "") or "").replace("+", "").strip()


def _outreach_allowed(to: str) -> bool:
    """Proaktif mesaj gonderimi icin izin kontrolu.

    Kural: OUTREACH_ENABLED=false iken SADECE admin (Neo) outreach alabilir.
    Yani Neo'ya "system durum", "sync bitti" gibi bilgi mesaji gidebilir.
    Diger tum numaralara blok + outreach_pending'e kayit.
    """
    if OUTREACH_ENABLED:
        return True  # Neo flag acmissa her yere izinli
    clean_to = (to or "").replace("+", "").strip()
    if ADMIN_PHONE_ENV and clean_to == ADMIN_PHONE_ENV:
        return True  # Admin'e her zaman
    return False


async def _block_outreach(to: str, text: str, reason: str = "") -> bool:
    """Outreach blok edildi — outreach_pending tablosuna yaz, Neo gozden gecirir."""
    clean_to = (to or "").replace("+", "").strip()
    phone_suffix = clean_to[-4:] if len(clean_to) >= 4 else "?"
    logger.warning(
        f"🔒 OUTREACH BLOCK — Neo onayi yok. to=...{phone_suffix} "
        f"reason={(reason or 'unspec')[:60]} text={text[:80]!r}"
    )
    try:
        from db_pool import db_execute
        await db_execute(
            """INSERT INTO outreach_pending (to_phone, text, reason, status, blocked_at)
               VALUES ($1, $2, $3, 'pending', NOW())""",
            clean_to, (text or "")[:2000], (reason or "")[:200],
        )
    except Exception as e:
        logger.debug(f"outreach_pending INSERT hatasi: {e}")
    return False
# DB URL merkezi kaynak — db_pool.py'dan (hardcoded DSN kaldırıldı)
from db_pool import DB_URL as DATABASE_URL
ANTHROPIC_KEY      = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_KEY         = os.getenv("OPENAI_API_KEY", "")
AGENT_API_KEY      = os.getenv("AGENT_API_KEY", "")  # /agent endpoint guvenlik

# ── DB POOL (paylasilan) ────────────────────────────────────────────────────
# OTURUM 22.3 (21 Nisan) — duplicate db wrapper'lar kaldirildi.
# get_db_pool() bridge'in 12 yerinde hala kullaniliyor (API uyumu icin korundu).
# db_fetch/fetchrow/fetchval/execute -> db_pool.py'dan import (tek kaynak).
from db_pool import get_pool as _shared_get_pool, db_fetch, db_fetchrow, db_fetchval, db_execute

async def get_db_pool():
    """Merkezi pool — db_pool.py'dan (tüm proje tek pool kullanır)."""
    return await _shared_get_pool()


# Oturum Mentenans (21 Nisan 19:15) — Test mode tespit (routing_stats kirlenmesin)
# Genisleme 10 May (Neo direktif): test_mode.is_test_context() ContextVar de okunur.
def _is_test_mode() -> bool:
    """Test modu aktif mi?
    - FERMAT_TEST_MODE=1 env (global override)
    - test_mode.is_test_context() (ContextVar: [TEST:id] marker veya test_phone)
    """
    import os as _os_tm
    if bool(_os_tm.getenv("FERMAT_TEST_MODE")):
        return True
    try:
        from test_mode import is_test_context as _itc
        if _itc():
            return True
    except Exception:
        pass
    return False


# OTURUM 22.6 (21 Nisan) — Fire-and-forget task guvenlik sarmalayicisi
# Exception silently swallowed sorunu icin: BG task hata verdiginde loglanir.
def _safe_background_task(coro, label: str = "bg"):
    """asyncio.create_task sarmalayicisi — exception'i log'lar, connection leak'i onler.

    Kullanim: _safe_background_task(run_extraction_background(...), label="insight")
    """
    async def _wrapper():
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as _bg_e:
            from loguru import logger as _bg_logger
            _bg_logger.warning(f"  [BG-TASK:{label}] hata (yutuldu, pool leak riski minimize): {_bg_e}")
    return asyncio.create_task(_wrapper())


# ── Startup / Shutdown ────────────────────────────────────────────────────────

# 25.23 — Cerebras paid tier flag (Quality cron + diğer cron'lar için)
_CEREBRAS_AVAIL_FLAG = bool(os.getenv("CEREBRAS_API_KEY"))


async def _run_scheduled_tasks():
    """Zamanlanmış görevler — daily report + sentiment + yoklama sync + analytics cache + eyotek sync."""
    from datetime import datetime
    import time as _boot_ts
    _boot_time = _boot_ts.time()  # Sistem açılış zamanı
    _eyotek_synced = False  # Açılıştan 1 saat sonra bir kez
    last_attendance_sync_hour = -1
    last_cache_refresh_ts = 0.0
    while True:
        try:
            now = datetime.now()

            # Analytics cache refresh — 30 dakikada bir (Oturum 18)
            # 10 kategori hesaplar (ogretmen, etut, devamsizlik vb); bridge cache-hit hizli cevap
            import time as _time
            if _time.time() - last_cache_refresh_ts > 1800:
                try:
                    from analytics_cache import ensure_cache
                    await ensure_cache(max_age_minutes=30)
                    last_cache_refresh_ts = _time.time()
                    logger.debug("📦 Analytics cache refresh edildi")
                except Exception as e:
                    logger.warning(f"Analytics cache hatası: {e}")
            # Günlük rapor — 20:00'da
            if now.hour == 20 and now.minute < 10:
                try:
                    from daily_report import generate_and_send_report
                    await generate_and_send_report()
                    logger.info("📊 Günlük rapor gönderildi")
                except Exception as e:
                    logger.warning(f"Günlük rapor hatası: {e}")
                # Classroom Management günlük raporu (22 Nisan Neo vizyonu)
                try:
                    from classroom_metrics import build_classroom_report
                    _cls_rep = await build_classroom_report()
                    if _cls_rep and len(_cls_rep) > 50:
                        # Neo'ya WP gonder
                        await send_wa_message("905051256802", _cls_rep,
                                              _outreach=True, _reason="classroom_daily")
                        logger.info("🎓 Classroom raporu Neo'ya gönderildi")
                except Exception as e:
                    logger.warning(f"Classroom rapor hatası: {e}")
                # Time-of-day analytics haftalık (Pazartesi 20:00)
                # 23 Nisan Neo fikri — peak saat, intent dağılımı
                try:
                    if now.weekday() == 0:  # Pazartesi
                        from time_analytics import build_time_report
                        _time_rep = await build_time_report(days=7)
                        if _time_rep and len(_time_rep) > 100:
                            await send_wa_message("905051256802", _time_rep,
                                                  _outreach=True, _reason="time_analytics_weekly")
                            logger.info("⏰ Haftalık time analytics Neo'ya gönderildi")
                except Exception as e:
                    logger.warning(f"Time analytics rapor hatası: {e}")
                # 25.40j (Neo direktif) — Haftalık konuşma kalite taraması (Pazartesi 20:00)
                # Cerebras 70B son 7 gun konuşmaları skorlar, alarm tetiklenirse Neo'ya WP rapor
                try:
                    if now.weekday() == 0:  # Pazartesi
                        from conversation_quality_analyzer import (
                            fetch_conversations as _qa_fetch,
                            analyze_burst as _qa_analyze,
                            aggregate as _qa_agg,
                            persist_to_db as _qa_persist,
                            check_alarm_and_notify as _qa_alarm,
                        )
                        try:
                            from cerebras_handler import CerebrasClient as _QClient
                            _qclient = _QClient()
                        except Exception:
                            from groq_handler import GroqClient as _QClient
                            _qclient = _QClient()
                        _qbursts = await _qa_fetch(hours=168, min_turns=3)  # 7 gun
                        _qbursts = _qbursts[:80]  # max 80 konusma (~$0.40)
                        _qresults = []
                        for _qb in _qbursts:
                            _qr = await _qa_analyze(_qclient, _qb)
                            if _qr:
                                _qresults.append(_qr)
                        _qreport = _qa_agg(_qresults)
                        _qreport["_meta"] = {"hours": 168, "auto": True}
                        # Alarm + persist
                        _qalarm = await _qa_alarm(_qreport, run_id=None)
                        await _qa_persist(_qreport, "scheduled_weekly", 168, _qalarm, _qresults)
                        logger.info(f"📊 Haftalik kalite tarama: {len(_qresults)} konusma, "
                                    f"avg={_qreport.get('ortalama_pedagojik_puan')}, alarm={_qalarm}")
                except Exception as e:
                    logger.warning(f"Haftalik kalite tarama hatasi: {e}")

                # Haftalık Jarvis insight (Pazartesi 20:00)
                try:
                    if now.weekday() == 0:
                        from jarvis_admin import build_neo_morning_brief
                        from feedback_loop import weekly_report
                        _j = await build_neo_morning_brief()
                        _fb = await weekly_report()
                        _extra = f"\n\n📊 *Haftalık Feedback:* {_fb.get('total',0)} sinyal · pozitif oranı %{int(_fb.get('sentiment_ratio',0)*100)}"
                        await send_wa_message("905051256802", _j + _extra,
                                              _outreach=True, _reason="jarvis_weekly")
                        logger.info("🤖 Haftalık Jarvis brief Neo'ya gönderildi")
                except Exception as e:
                    logger.warning(f"Jarvis brief hatası: {e}")

            # Sabah 08:00 — ödev hatırlatıcı
            if now.hour == 8 and now.minute < 10:
                try:
                    from odev_scheduler import get_due_reminders, format_reminder, mark_reminded
                    from collections import defaultdict
                    due = await get_due_reminders()
                    by_student = defaultdict(list)
                    for o in due:
                        by_student[o["ogrenci_soz_no"]].append(o)
                    sent = 0
                    for soz, ods in by_student.items():
                        if not ods:
                            continue
                        msg = format_reminder(ods[0].get("full_name", ""), ods)
                        phone = ods[0].get("phone")
                        if phone and msg:
                            try:
                                await send_wa_message(phone, msg, _outreach=True, _reason="odev_reminder")
                                for o in ods:
                                    await mark_reminded(o["id"])
                                sent += 1
                            except Exception:
                                pass
                    if sent:
                        logger.info(f"📝 Ödev hatırlatma: {sent} öğrenciye gönderildi")
                except Exception as e:
                    logger.warning(f"Ödev hatırlatma hatası: {e}")
            # Gece 03:00 — student_profile_v2 nightly refresh
            if now.hour == 3 and now.minute < 10:
                try:
                    from student_profile_v2 import refresh_all_profiles
                    await refresh_all_profiles()
                except Exception as e:
                    logger.warning(f"profile refresh hatası: {e}")

            # ── Oturum 25.9 SCHEDULER ──
            # Gece 02:00 — Atlas-2 prompt iyilestirme analizi
            if now.hour == 2 and now.minute < 10:
                try:
                    from prompt_optimizer import analyze_and_suggest
                    result = await analyze_and_suggest(hours=24)
                    logger.info(f"🤖 Atlas-2 oneri analizi: {result}")
                except Exception as e:
                    logger.warning(f"Atlas-2 hatası: {e}")

            # 25.23 — Saatte bir: Spend monitoring (Cerebras + Claude bütçe takibi)
            # Bu Eylül 120 öğrenci icin kritik. Maliyet patlamasini engeller.
            if now.minute < 5 and not getattr(_run_scheduled_tasks, f'_spend_h_{now.hour}', False):
                setattr(_run_scheduled_tasks, f'_spend_h_{now.hour}', True)
                # Diger saatleri sıfırla
                for _h in range(24):
                    if _h != now.hour:
                        if hasattr(_run_scheduled_tasks, f'_spend_h_{_h}'):
                            delattr(_run_scheduled_tasks, f'_spend_h_{_h}')
                try:
                    from db_pool import db_fetch as _spend_fetch
                    PRICES = {
                        "claude":         {"in": 3.0,  "out": 15.0},
                        "cerebras_8b":    {"in": 0.10, "out": 0.10},
                        "cerebras_120b":  {"in": 0.30, "out": 0.50},
                        "cerebras_235b":  {"in": 0.60, "out": 0.80},  # LEGACY 25.49 emekli — geçmiş kayıt
                        "cerebras":       {"in": 0.30, "out": 0.50},
                        "groq":           {"in": 0.59, "out": 0.79},
                    }
                    rows = await _spend_fetch(
                        """SELECT response_source, COUNT(*) as cnt,
                                  COALESCE(SUM(token_input),0) as ti,
                                  COALESCE(SUM(token_output),0) as to_
                           FROM usage_log
                           WHERE created_at >= CURRENT_DATE
                           GROUP BY response_source"""
                    )
                    total_cost = 0.0
                    breakdown = []
                    for r in (rows or []):
                        src = r.get("response_source") or "unknown"
                        p = PRICES.get(src, {"in": 0, "out": 0})
                        cost = (r["ti"] * p["in"] + r["to_"] * p["out"]) / 1_000_000.0
                        total_cost += cost
                        breakdown.append(f"{src}={r['cnt']}msg/${cost:.3f}")
                    logger.info(f"💰 Bugünkü maliyet: ${total_cost:.3f} | " + " ".join(breakdown))
                    # Eşik kontrolleri
                    if total_cost > 10.0:
                        # Yüksek günlük maliyet — Neo'ya bildir
                        try:
                            await send_wa_message(
                                "905051256802",
                                f"⚠️ *YÜKSEK GÜNLÜK MALİYET*\n\nBugünkü API harcaması: *${total_cost:.2f}*\n\n"
                                + "\n".join(f"• {b}" for b in breakdown[:5])
                                + f"\n\nNormal günlük seviye ~$2-5. İncele.",
                                _outreach=True, _reason="spend_alert_high"
                            )
                            logger.warning(f"💸 Spend alert ($10+) Neo'ya gönderildi: ${total_cost:.2f}")
                        except Exception as _e:
                            logger.warning(f"Spend alert WP gönderilemedi: {_e}")
                    elif total_cost > 5.0:
                        logger.warning(f"💸 Günlük maliyet $5+: ${total_cost:.2f} (eşik takibinde)")
                except Exception as e:
                    logger.debug(f"Spend monitor hatası: {e}")

            # 25.23 — Her 5 dakikada: Health check (DB pool + Cerebras availability)
            # Sessiz kontrol — sadece sorun varsa log ve bildirim
            _hc_key = f"_hc_{now.hour}_{now.minute // 5}"
            if not getattr(_run_scheduled_tasks, _hc_key, False):
                setattr(_run_scheduled_tasks, _hc_key, True)
                # Eski health check key'lerini temizle
                for _attr in list(vars(_run_scheduled_tasks).keys() if hasattr(_run_scheduled_tasks, '__dict__') else []):
                    if _attr.startswith('_hc_') and _attr != _hc_key:
                        try: delattr(_run_scheduled_tasks, _attr)
                        except: pass
                try:
                    from db_pool import db_fetchval as _hc_fetchval
                    # DB ping
                    db_ok = False
                    try:
                        v = await _hc_fetchval("SELECT 1")
                        db_ok = (v == 1)
                    except Exception:
                        pass
                    # Cerebras ping (env'de var mı + import OK mi)
                    cerebras_ok = bool(os.getenv("CEREBRAS_API_KEY"))
                    if not db_ok:
                        logger.error("🚨 HEALTH: DB pool yanit vermiyor!")
                        try:
                            await send_wa_message(
                                "905051256802",
                                "🚨 *KRİTİK*: DB pool yanit vermiyor (health check 5dk).",
                                _outreach=True, _reason="health_db_down"
                            )
                        except Exception:
                            pass
                except Exception as _e:
                    logger.debug(f"Health check hatası: {_e}")

            # 25.24 — Pazar 04:30: DB retention policy (eski kayitlari arsivle/sil)
            if now.weekday() == 6 and now.hour == 4 and now.minute >= 25 and now.minute < 35:
                if not getattr(_run_scheduled_tasks, '_retention_done_today', False):
                    setattr(_run_scheduled_tasks, '_retention_done_today', True)
                    try:
                        from db_retention import run_full_retention
                        result = await run_full_retention()
                        logger.info(f"🗂️  DB retention: {result}")
                        # Neo'ya bildir
                        try:
                            ac = result.get("agent_conversations", {})
                            archived = ac.get("archived", 0)
                            if archived > 0:
                                await send_wa_message(
                                    "905051256802",
                                    f"🗂️ *Haftalık DB temizliği*\n\n"
                                    f"Arşivlenen: {archived} eski konuşma\n"
                                    f"routing_stats / usage_log / query_cache temizlendi.",
                                    _outreach=True, _reason="db_retention"
                                )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.warning(f"DB retention hata: {e}")
            # Pazartesi flag reset
            if now.weekday() == 0 and now.hour == 0:
                if hasattr(_run_scheduled_tasks, '_retention_done_today'):
                    delattr(_run_scheduled_tasks, '_retention_done_today')

            # 25.46+ TOPLULUK 24h RETENTION (Neo 18 May direktif):
            # "Topluluk mesajlari 24 saatlik periyotlarda korunuyor olsun —
            # guvenlik kamerasi mantigi gibi. Ilk asamada guvenlik veya
            # yanlis kullanim risklerini daha kolay kontrol ederiz."
            # Her saatin :07 dakikasinda 24+ saat eski mesajlari sil.
            if now.minute >= 5 and now.minute < 10:
                _hkey = f"_topluluk_clean_h_{now.hour}"
                if not getattr(_run_scheduled_tasks, _hkey, False):
                    setattr(_run_scheduled_tasks, _hkey, True)
                    # Diger saatleri sıfırla — yarinki saat tekrar tetiklensin
                    for _h in range(24):
                        if _h != now.hour:
                            _kk = f"_topluluk_clean_h_{_h}"
                            if hasattr(_run_scheduled_tasks, _kk):
                                delattr(_run_scheduled_tasks, _kk)
                    try:
                        from db_pool import db_execute as _db_exec
                        _del_res = await _db_exec(
                            "DELETE FROM topluluk_messages "
                            "WHERE created_at < NOW() - INTERVAL '24 hours'"
                        )
                        # asyncpg DELETE 'DELETE N' formatinda dondur
                        _n = 0
                        try:
                            _n = int(str(_del_res).rsplit(" ", 1)[-1])
                        except Exception:
                            pass
                        if _n > 0:
                            logger.info(f"🗑️  Topluluk retention: {_n} eski mesaj silindi (24h+)")
                    except Exception as _te:
                        logger.warning(f"Topluluk retention hata: {_te}")

            # 25.23-final — Günde bir 09:00: Disk + DB doluluk monitoring
            # 120 ogrenci × 30K mesaj/ay → DB hizla buyur, log dosyalari taşar
            if now.hour == 9 and now.minute < 10 and not getattr(_run_scheduled_tasks, '_disk_today', False):
                setattr(_run_scheduled_tasks, '_disk_today', True)
                # Tarihi unut yarın yeni gün başlasın
                if now.hour == 0:
                    if hasattr(_run_scheduled_tasks, '_disk_today'):
                        delattr(_run_scheduled_tasks, '_disk_today')
                try:
                    import shutil
                    total, used, free = shutil.disk_usage("/")
                    pct = int(used / total * 100)
                    free_gb = free // (1024**3)
                    logger.info(f"💾 Disk: {pct}% used, {free_gb}GB free")
                    if pct > 85:
                        try:
                            await send_wa_message(
                                "905051256802",
                                f"🚨 *DISK ALERT*: %{pct} dolu, sadece {free_gb}GB serbest. Temizlik gerek.",
                                _outreach=True, _reason="disk_alert"
                            )
                        except Exception:
                            pass
                    # DB boyutu
                    try:
                        from db_pool import db_fetchval as _disk_fv
                        db_size = await _disk_fv("SELECT pg_database_size('fermatai')")
                        db_mb = (db_size or 0) // (1024 * 1024)
                        logger.info(f"💾 DB boyutu: {db_mb} MB")
                    except Exception:
                        pass
                except Exception as e:
                    logger.debug(f"Disk monitor hatası: {e}")
            # Gece yarısı _disk_today flag reset
            if now.hour == 0 and now.minute < 10:
                if hasattr(_run_scheduled_tasks, '_disk_today'):
                    delattr(_run_scheduled_tasks, '_disk_today')

            # 25.23 — Pazartesi 20:30: Haftalik konusma kalite analizi (Cerebras 120b)
            if now.weekday() == 0 and now.hour == 20 and now.minute >= 30 and now.minute < 40:
                try:
                    from conversation_quality_analyzer import build_bursts, analyze_burst, aggregate
                    if _CEREBRAS_AVAIL_FLAG:
                        from cerebras_handler import CerebrasClient as _QC
                        _qc = _QC()
                    else:
                        from groq_handler import GroqClient as _QC
                        _qc = _QC()
                    _bursts = await build_bursts(hours=168, max_bursts=30)
                    _qres = []
                    for _b in _bursts[:20]:
                        _r = await analyze_burst(_qc, _b)
                        if _r: _qres.append(_r)
                    if _qres:
                        _agg = aggregate(_qres)
                        _msg = (
                            f"📊 *Haftalık Kalite Raporu*\n\n"
                            f"• Analiz edilen: {len(_qres)} konuşma\n"
                            f"• Ortalama puan: *{_agg.get('avg_pedagojik', '?')}/10*\n"
                            f"• Frustration: {_agg.get('frustration_count', 0)}\n"
                            f"• Bot hatası: {_agg.get('bot_error_count', 0)}\n"
                            f"• Eksik pattern: {_agg.get('missing_pattern_count', 0)}"
                        )
                        await send_wa_message("905051256802", _msg,
                                              _outreach=True, _reason="quality_weekly")
                        logger.info(f"📊 Haftalık kalite raporu Neo'ya: {len(_qres)} konuşma")
                except Exception as e:
                    logger.warning(f"Haftalık kalite hatası: {e}")

            # Pazar 04:00 — haftalik predictive model batch (tum aktif ogrenciler)
            if now.weekday() == 6 and now.hour == 4 and now.minute < 10:
                try:
                    from predictive_model import predict_all_students
                    result = await predict_all_students(limit=200)
                    logger.info(f"📈 Haftalik puan tahmin: {result}")
                except Exception as e:
                    logger.warning(f"Predictive batch hatası: {e}")

            # Gece 03:30 — knowledge graph mastery refresh (ELO -> mastery)
            if now.hour == 3 and now.minute >= 25 and now.minute < 35:
                try:
                    from knowledge_graph import update_student_mastery_from_elo
                    rows = await db_fetch(
                        "SELECT DISTINCT soz_no FROM student_topic_elo WHERE games_played > 0"
                    )
                    cnt = 0
                    for r in (rows or []):
                        try:
                            await update_student_mastery_from_elo(r['soz_no'])
                            cnt += 1
                        except Exception:
                            pass
                    if cnt > 0:
                        logger.info(f"🧠 Knowledge graph mastery refresh: {cnt} ogrenci")
                except Exception as e:
                    logger.warning(f"KG mastery refresh hatası: {e}")

            # Duygu/motivasyon takibi — 6 saatte bir (08, 14, 20)
            if now.hour in (8, 14, 20) and now.minute < 10:
                try:
                    from sentiment_tracker import check_and_alert_rehber
                    await check_and_alert_rehber()
                    logger.info("🧠 Duygu takibi kontrol edildi")
                except Exception as e:
                    logger.warning(f"Duygu takibi hatası: {e}")

            # Yoklama sync — günde 4 kez (09, 13, 19, 23)
            # Bot koruması icin: günlük 4 hit yeterli, anlik scrape YOK
            if now.hour in (9, 13, 19, 23) and now.minute < 10 and last_attendance_sync_hour != now.hour:
                last_attendance_sync_hour = now.hour
                try:
                    from sync_attendance import run_attendance_sync, ensure_data_freshness_table
                    await ensure_data_freshness_table()
                    days = 1 if now.hour != 23 else 2  # 23:00'da 2 gun geriye
                    result = await run_attendance_sync(days=days)
                    logger.info(f"📋 Yoklama sync ({now.hour}:00): {result}")
                    # Oturum 23 (Neo sessiz fail audit): Sync fail olursa Neo'ya bildir.
                    # Günlük 1 kez bildirim — spam önleme (09:00 slot'unda)
                    if not result.get("success") and now.hour == 9:
                        reason = result.get("reason", "bilinmeyen hata")[:200]
                        # Oturum 25.10d (Neo): admin_notify - gunduz WP, gece sadece panel
                        try:
                            from admin_notify import notify_admin
                            await notify_admin(
                                severity="warning",
                                category="eyotek",
                                title="⚠️ Yoklama sync başarısız",
                                body=(f"Saat: {now.strftime('%H:%M')}\nSebep: {reason}\n\n"
                                      "Eyotek sayfa yapısı değişmiş veya session kırılmış olabilir. "
                                      "Chrome CDP'de yoklama sayfasını manuel kontrol et."),
                                metadata={"job": "yoklama_sync", "hour": now.hour},
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"Yoklama sync hatası: {e}")

            # Oturum 23 (Neo audit): SYNC HEALTH CHECK — her gün 09:15'te
            # data_freshness tablosunda son sync 48+ saat olan modülleri tara,
            # Neo'ya sağlık raporu at. Sessiz başarısızlığı TEKRAR ÖNLER.
            if now.hour == 9 and 15 <= now.minute < 25 and last_attendance_sync_hour == 9:
                try:
                    from db_pool import db_fetch
                    _stale = await db_fetch("""
                        SELECT module, description, last_sync,
                               EXTRACT(EPOCH FROM (NOW() - last_sync)) / 3600 AS saat_gecmis
                        FROM fermat.data_freshness
                        WHERE last_sync IS NOT NULL
                          AND refresh_type IN ('daily', 'hourly')
                          AND last_sync < NOW() - INTERVAL '30 hours'
                        ORDER BY last_sync ASC
                    """)
                    _never = await db_fetch("""
                        SELECT module, description
                        FROM fermat.data_freshness
                        WHERE last_sync IS NULL
                          AND refresh_type IN ('daily', 'hourly', 'weekly')
                    """)
                    if _stale or _never:
                        lines = ["🏥 *Sync Health Raporu*", ""]
                        if _stale:
                            lines.append("*Eski senkronizasyonlar (30+ saat):*")
                            for s in _stale:
                                lines.append(f"  • `{s['module']}` — {int(s['saat_gecmis'])}h önce ({s['description'][:40]})")
                            lines.append("")
                        if _never:
                            lines.append("*Hiç senkronize olmamış:*")
                            for n in _never:
                                lines.append(f"  • `{n['module']}` ({n['description'][:40]})")
                            lines.append("")
                        lines.append("_Manuel kontrol veya scraper fix gerekebilir._")
                        _health_msg = "\n".join(lines)
                        await send_wa_message("905051256802", _health_msg,
                                              _outreach=True, _reason="sync_health_check")
                        logger.info(f"🏥 Sync health: {len(_stale)} eski, {len(_never)} hiç sync değil → Neo'ya bildirim")
                except Exception as e:
                    logger.warning(f"Sync health check hatası: {e}")

            # Eyotek etüt sync — Oturum 23 (Neo audit): "açılıştan +1h" çok kırılgandı,
            # bridge 1h kalmalı VE scheduler tam pencerede denk gelmeli. Artık GECELIK
            # sabit slot: 02:30 (Eyotek boş, scraper rahat çalışır, gündüz mesaj trafiği yok).
            # Ayrıca açılıştan 5 dk sonra da BİR defa çalıştır (yeni kurulum durumunda).
            if now.hour == 2 and 30 <= now.minute < 40 and not _eyotek_synced:
                _eyotek_synced = True
                try:
                    from eyotek_knowledge.scrapers.etut_sync import sync_etut
                    r = await sync_etut()
                    if r["success"]:
                        logger.info(f"📦 Eyotek etüt sync (gece 02:30): {r['inserted']} yeni kayıt")
                    else:
                        logger.warning(f"Eyotek etüt sync hata: {r.get('error')}")
                        # Oturum 25.10d (Neo): admin_notify — GECE WP YASAK, sadece panel
                        # Onceden 02:30'da WP atip Neo'yu uyandiriyordu (5:38 sabah 26 Nis)
                        try:
                            from admin_notify import notify_admin
                            await notify_admin(
                                severity="warning",
                                category="eyotek",
                                title="⚠️ Gece etüt sync başarısız (02:30)",
                                body=f"Sebep: {r.get('error', 'bilinmiyor')[:200]}",
                                metadata={"job": "etut_sync", "time": "02:30"},
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(f"Eyotek sync hatası: {e}")
                # Yeni gün için flag reset — ertesi gün tekrar çalışsın
            if now.hour == 3:
                _eyotek_synced = False  # 03:00'ta flag reset, ertesi 02:30 için hazır

        except Exception as e:
            logger.error(f"Scheduler hatası: {e}")
        # 10 dakikada bir kontrol et
        await asyncio.sleep(600)


async def _run_conversation_html_updater():
    """Konuşma HTML'ini her 2 dakikada bir günceller."""
    import subprocess
    await asyncio.sleep(30)  # İlk başta 30s bekle
    while True:
        try:
            # conversation_viewer.py'yi subprocess olarak çağır (asyncio'yu bloklamaz)
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "conversation_viewer.py",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=60)
            logger.debug("📄 Konuşma HTML güncellendi (logs/conversations.html)")
        except Exception as e:
            logger.debug(f"HTML update hatası: {e}")
        # 2 dakikada bir güncelle
        await asyncio.sleep(120)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlangıç ve kapanış yönetimi."""
    # ── Başlangıç ──────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("🚀  FermatAI WhatsApp Bridge başlatılıyor")
    logger.info("=" * 60)

    _ok = "✅"
    _warn = "⚠️ "

    # Kritik config kontrolü
    checks = [
        (bool(ANTHROPIC_KEY),      _ok if ANTHROPIC_KEY else _warn, "ANTHROPIC_API_KEY"),
        (bool(DATABASE_URL),       _ok if DATABASE_URL  else _warn, "DATABASE_URL"),
        (bool(WA_ACCESS_TOKEN),    _ok if WA_ACCESS_TOKEN else _warn, "WA_ACCESS_TOKEN"),
        (bool(WA_PHONE_NUMBER_ID), _ok if WA_PHONE_NUMBER_ID else _warn, "WA_PHONE_NUMBER_ID"),
        (bool(OPENAI_KEY),         _ok if OPENAI_KEY else "ℹ️ ", "OPENAI_API_KEY (opsiyonel — Whisper)"),
        (bool(WA_APP_SECRET),      _ok if WA_APP_SECRET else "ℹ️ ", "WA_APP_SECRET (opsiyonel — imza doğrulama)"),
    ]
    has_errors = False
    for ok, icon, name in checks:
        logger.info(f"  {icon}  {name}")
        if not ok and icon == _warn:
            has_errors = True

    # Session dosyası var mı?
    session_file = Path(os.getenv("SESSION_FILE", ".eyotek_session.json"))
    if session_file.exists():
        logger.info(f"  ✅  Eyotek session: {session_file}")
    else:
        logger.warning(f"  ⚠️   Eyotek session bulunamadı ({session_file}) — yazma işlemleri başarısız olacak")

    if has_errors:
        logger.warning("  Eksik config değerleri var — .env dosyasını kontrol edin")
    else:
        logger.info("  Tüm kritik ayarlar mevcut")

    logger.info(f"  📡  Port: {os.getenv('BRIDGE_PORT', '8000')}")
    logger.info("=" * 60)

    # ── DB Pool Warmup ────────────────────────────────────────────────────────
    try:
        await get_db_pool()
        logger.info("  💾  DB pool hazir (min=2, max=10)")
    except Exception as e:
        logger.warning(f"  ⚠️  DB pool init hatasi: {e}")

    # ── Query Cache tablosu (Oturum 22.1) ────────────────────────────────────
    try:
        from query_cache import init_db as qc_init, cleanup_expired as qc_cleanup
        await qc_init()
        _removed = await qc_cleanup()
        logger.info(f"  🎯  Query cache hazir (eski {_removed} kayit silindi)")
    except Exception as e:
        logger.warning(f"  ⚠️  Query cache init hatasi: {e}")

    # ── Hack tracker (DB persistent jailbreak blok) 22.1d ────────────────────
    try:
        from hack_tracker import init_db as ht_init, cleanup_expired as ht_cleanup
        await ht_init()
        _rem = await ht_cleanup()
        logger.info(f"  🛡️  Hack tracker hazir ({_rem} eski kayit silindi)")
    except Exception as e:
        logger.warning(f"  ⚠️  Hack tracker init hatasi: {e}")

    # ── Tool Performance Tracking (25.37+ Neo audit #3) ──────────────────────
    # 118 tool için süre + success log → optimize edilebilsin
    try:
        from tool_perf import ensure_table as _tp_init
        await _tp_init()
        logger.info("  📊  Tool perf tracker hazir (tool_usage_log)")
    except Exception as e:
        logger.warning(f"  ⚠️  Tool perf init hatasi: {e}")

    # ── Behavior rules + Active recall (25.37 ensure DB) ─────────────────────
    try:
        from behavior_rules import ensure_table as _br_init
        await _br_init()
        from active_recall import ensure_table as _ar_init
        await _ar_init()
    except Exception as e:
        logger.debug(f"  behavior/recall init: {e}")

    # ── Log filter (hassas veri maskeleme) 22.1d ─────────────────────────────
    try:
        from utils.log_filter import install_log_filter
        install_log_filter()
    except Exception as e:
        logger.warning(f"  ⚠️  Log filter install hatasi: {e}")

    # ── Deployment Kaydı (her restart'ta otomatik) ──────────────────────────
    # KALDIGIM.md'den son oturum özetini notes alanına yaz — bot "ne değişti"
    # sorusuna kesin cevap verebilsin (Oturum 21 Talimat #74 fix).
    try:
        _pool_dep = await get_db_pool()
        async with _pool_dep.acquire() as _conn_dep:
            # Prompt token sayısını hesapla
            try:
                from fermat_core_agent import SYSTEM_PROMPT
                _pt = len(SYSTEM_PROMPT) // 3
            except Exception:
                _pt = 0

            # KALDIGIM.md'den son oturum bloğu çek
            _notes = "bridge restart"
            _version = "auto"
            try:
                from pathlib import Path as _P
                # Oturum 25 VPS fix: Dinamik path (laptop Windows / VPS Linux ikisi de calisir)
                _kp = _P(__file__).resolve().parent.parent / "KALDIGIM.md"
                if _kp.exists():
                    _full = _kp.read_text(encoding="utf-8")
                    # İlk H1'den sonra ilk H2 (🌟/🔥 ile başlayan en son oturum) blokunu al
                    import re as _re_dep
                    # En son güncelleme satırı version olsun
                    _v_match = _re_dep.search(r'Son güncelleme:\s*([^\n]+)', _full)
                    if _v_match:
                        _version = _v_match.group(1).strip()[:80]
                    # İlk ## başlıktan sonra 2500 karakter özet (son oturum)
                    _h2_match = _re_dep.search(r'\n## [🌟🔥⚡🎯🌐🔧💻][^\n]*\n([\s\S]{0,2500})', _full)
                    if _h2_match:
                        _notes = _h2_match.group(0)[:3000]
                    else:
                        # Fallback — ilk 2000 char'ı al
                        _notes = _full[:2000]
            except Exception as _kerr:
                logger.debug(f"  KALDIGIM okuma hatası: {_kerr}")

            await _conn_dep.execute(
                "INSERT INTO deployments (version, notes, prompt_tokens) VALUES ($1, $2, $3)",
                _version, _notes, _pt
            )
        logger.info(f"  📦  Deployment kaydedildi (v={_version[:40]}, notes={len(_notes)}c, prompt ~{_pt}t)")
    except Exception as _dep_err:
        logger.debug(f"  Deployment kayit hatasi: {_dep_err}")

    # ── Ollama Warmup + Keep-Alive ──
    # 25.44 (Neo bug 12 May 18:57 — bot self-analysis iter3):
    # VPS'te Ollama SADECE embedding (bge-m3, nomic-embed-text) kurulu.
    # qwen2.5:7b YOK — eski warmup her 5dk yok olan modeli yüklemeye çalışıp
    # "RAM'da" diye YALAN log atıyordu. Şimdi: önce modelin var olduğunu
    # doğrula, yoksa "embedding-only" mesajıyla atla.
    try:
        async def _ollama_ping(tag: str = "warmup"):
            model = os.getenv('OLLAMA_MODEL', '').strip()
            if not model:
                # LLM yok, embedding-only VPS — warmup gereksiz
                logger.info(f"  💤  Ollama {tag} ATLANDI: LLM model env tanımsız, embedding-only mod")
                return
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    # Önce model var mı kontrol et
                    r_tags = await client.get('http://localhost:11434/api/tags')
                    available = []
                    if r_tags.status_code == 200:
                        available = [m.get('name','') for m in (r_tags.json() or {}).get('models', [])]
                    if model not in available and f"{model}:latest" not in available:
                        logger.info(f"  💤  Ollama {tag} ATLANDI: '{model}' kurulu değil "
                                    f"(mevcut: {available})")
                        return
                    # Gerçek warmup
                    r = await client.post('http://localhost:11434/api/chat', json={
                        'model': model,
                        'messages': [{'role':'user','content':'ok'}],
                        'stream': False,
                        'options': {'num_predict': 2},
                        'keep_alive': '15m',
                    })
                    if r.status_code == 200:
                        logger.info(f"  🔥  Ollama {tag} tamamlandi ({model} RAM'da)")
                    else:
                        logger.warning(f"  ⚠️  Ollama {tag} fail {r.status_code}: {r.text[:100]}")
            except Exception as _ee:
                logger.debug(f"Ollama {tag} atlandi: {_ee}")

        async def _ollama_keepalive_loop():
            await asyncio.sleep(5)  # boot warmup'tan sonra
            await _ollama_ping("warmup")
            while True:
                await asyncio.sleep(600)  # her 10 dk (keep_alive 15dk'dan once)
                await _ollama_ping("keepalive")

        asyncio.create_task(_ollama_keepalive_loop())
    except Exception as _:
        pass

    # 22.1n-neo iş4: DB Schema cache warmup — Claude prompt'una enjekte edilecek
    try:
        async def _schema_warmup():
            try:
                from db_schema_cache import get_schema_cache
                data = await get_schema_cache()
                logger.info(f"  📊  DB schema cache warmup: {len(data)} tablo hazir")
            except Exception as _se:
                logger.debug(f"schema warmup atlandi: {_se}")
        asyncio.create_task(_schema_warmup())
    except Exception:
        pass

    # OTURUM 23.4 (21 Nisan) — Enrichment sanity check
    # Kritik tablolar hydrate degilse WARN yaz (ogrenilmesi zor hatalari onle)
    try:
        async def _enrichment_sanity():
            try:
                pool = await _shared_get_pool()
                async with pool.acquire() as _c:
                    pl = await _c.fetchval("SELECT count(*) FROM fermat.pedagoji_literatur") or 0
                    ak = await _c.fetchval("SELECT count(*) FROM anekdotlar") or 0
                    ps = await _c.fetchval("SELECT count(*) FROM fermat.pedagojik_sablonlar") or 0
                    rc = await _c.fetchval("SELECT count(*) FROM fermat.rag_content") or 0
                logger.info(
                    f"  🧠  Enrichment sanity: pedagoji={pl}, anekdot={ak}, sablon={ps}, rag={rc}"
                )
                if pl < 10 or ak < 15 or ps < 20:
                    logger.warning(
                        f"  ⚠  Enrichment tablolari eksik gorunuyor "
                        f"(beklenen: pl>=12, ak>=22, ps>=27) — hydrate gerekebilir"
                    )
            except Exception as _es:
                logger.debug(f"enrichment sanity atlandi: {_es}")
        asyncio.create_task(_enrichment_sanity())
    except Exception:
        pass

    # Classroom Management — DB schema + metrics (22 Nisan Neo vizyonu)
    try:
        async def _cm_bootstrap():
            try:
                from token_budget import ensure_schema as _cm_schema, ENFORCE_ACTIVE
                await _cm_schema()
                mode = "ENFORCE" if ENFORCE_ACTIVE else "OLCUM (pasif)"
                logger.info(f"  🎓  Classroom Management aktif — mod: {mode}")
            except Exception as _cms_e:
                logger.debug(f"  classroom bootstrap atlandi: {_cms_e}")
        asyncio.create_task(_cm_bootstrap())

        # 23 Nisan Jarvis Paket — 14 yeni modül schema bootstrap
        async def _jarvis_bootstrap():
            try:
                from student_profile_v2 import ensure_schema as _p_s
                from gamification import ensure_schema as _g_s
                from spaced_repetition import ensure_schema as _sr_s
                from odev_scheduler import ensure_schema as _od_s
                from feedback_loop import ensure_schema as _fb_s
                await _p_s(); await _g_s(); await _sr_s(); await _od_s(); await _fb_s()
                logger.info("  🤖  Jarvis paket schema hazir: profile_v2, gamification, spaced_rep, odev, feedback")
            except Exception as _je:
                logger.debug(f"  jarvis bootstrap atlandi: {_je}")
        asyncio.create_task(_jarvis_bootstrap())
    except Exception:
        pass

    # 22.1n-neo Fikir 2: Gece 03:00 precompute scheduler
    # 25.40r: Bu nokta lifespan basinda — leader election henuz yapilmadi.
    # Inline kontrol: REDIS yoksa zaten tek worker, calistir. REDIS varsa
    # daha sonra leader_only re-evaluate (asagida _is_singleton_leader = await is_leader())
    # Ama precompute_nightly'nin kendi schedule'inda 24 saat sleep var, bir restart'ta
    # tetiklenmez — kabul edilebilir cifte calisma riski cok dusuk. Yine de gate ekle.
    try:
        from precompute_nightly import nightly_scheduler_loop
        from singleton_leader import is_leader as _il
        # Hizli bir leader claim dene — eger lider degilsek nightly'i atla
        _early_leader = await _il()
        if _early_leader:
            _nightly_task = asyncio.create_task(nightly_scheduler_loop())
            logger.info("  🌙  Nightly precompute scheduler aktif (03:00, leader)")
        else:
            logger.info("  🌙  Nightly precompute SKIP (follower worker)")
    except Exception as _ne:
        logger.debug(f"nightly scheduler atlandi: {_ne}")

    # 22.1n-neo Paket A: HybridDict'leri Redis'ten hydrate (persistent state)
    try:
        from hybrid_state import is_redis_mode
        if is_redis_mode():
            total = 0
            for _hd, _name in [
                (_TEMP_BANS, "ban"),
                (_CAPACITY_COUNTS, "cap"),
                (_PHOTO_COUNTS, "photo"),
                (_CLAUDE_CALLS, "claude_burst"),
            ]:
                try:
                    total += await _hd.hydrate_from_redis()
                except Exception:
                    pass
            if total > 0:
                logger.info(f"  🔄  Hybrid state hydrate: toplam {total} key yuklendi")
    except Exception as _he:
        logger.debug(f"hydrate atlandi: {_he}")

    # ── 25.40r: Singleton Leader Election (workers>=2 hazirligi) ───────────
    # Bu worker leader mi? Sadece leader cron-like task'leri calistirir
    # (session_keeper, scheduled_tasks, html_updater, telafi, briefing, todo).
    # Memory mode'da her zaman True (tek worker = leader).
    # 25.40r-B1.3: start_leader_refresh HER WORKER'da calisir (leader-only DEGIL),
    # cunku eski leader oldugunde follower'lar takeover SETNX dener.
    _is_singleton_leader = True
    _leader_refresh_task = None
    try:
        from singleton_leader import is_leader, start_leader_refresh
        _is_singleton_leader = await is_leader()
        # Refresh+takeover monitor — her worker'da (leader=TTL refresh, follower=takeover dene)
        _leader_refresh_task = asyncio.create_task(start_leader_refresh())
    except Exception as _le:
        logger.warning(f"  Leader election atlandi (fail-open): {_le}")
        _is_singleton_leader = True  # fail-open

    # ── Zamanlanmış Görevler (LEADER ONLY) ─────────────────────────────────
    _scheduler_task = None
    _html_task = None
    _session_keeper_task = None
    if _is_singleton_leader:
        try:
            _scheduler_task = asyncio.create_task(_run_scheduled_tasks())
            _html_task = asyncio.create_task(_run_conversation_html_updater())
            logger.info("  ⏰  Zamanlanmış görevler aktif (günlük rapor 20:00, duygu takibi 6 saatte 1)")
            logger.info("  📄  Konuşma HTML otomatik güncelleniyor (2dk, logs/conversations.html)")
        except Exception as e:
            logger.warning(f"  Scheduler başlatılamadı: {e}")
    else:
        logger.info("  ⏰  Scheduler/HTML updater SKIP (follower worker)")

    # ── Session Keeper (Oturum 18, LEADER ONLY) — Eyotek CDP cakismasin ───
    if _is_singleton_leader:
        try:
            from session_keeper import session_keeper_loop as _sk_loop
            _session_keeper_task = asyncio.create_task(_sk_loop())
            logger.info("  🔐  Session Keeper aktif (Eyotek 3dk periyod, drop'ta WP admin bildirim)")
        except Exception as e:
            logger.warning(f"  Session Keeper baslatilamadi: {e}")
    else:
        logger.info("  🔐  Session Keeper SKIP (follower worker — Eyotek CDP cakismasi onlendi)")

    # ── İletişim Telafi Scheduler (B4, LEADER ONLY) ────────────────────────
    # 30dk periyod — bekleyen frustration_log kayıtlarını 10-21 saat arasında telafi eder
    _telafi_task = None
    if _is_singleton_leader:
        try:
            async def _telafi_loop():
                from frustration_telafi import check_and_send_telafi
                while True:
                    await asyncio.sleep(1800)  # 30dk
                    try:
                        result = await check_and_send_telafi(send_wa_func=send_wa_message)
                        if result.get("sent", 0) > 0:
                            logger.info(f"✨ Telafi döngüsü: {result['sent']} mesaj gönderildi")
                    except Exception as _te:
                        logger.debug(f"Telafi döngü hatası: {_te}")
            _telafi_task = asyncio.create_task(_telafi_loop())
            logger.info("  ✨  İletişim Telafi aktif (30dk periyod, 10-21 saat, 30dk-24h pencere)")
        except Exception as e:
            logger.warning(f"  Telafi scheduler baslatilamadi: {e}")

    # ── 25.28: F1 Teacher Briefing scheduler (15dk periyod, LEADER ONLY) ───
    _briefing_task = None
    if _is_singleton_leader:
        try:
            from teacher_briefing import briefing_scheduler_loop
            _briefing_task = asyncio.create_task(briefing_scheduler_loop())
            logger.info("  📋  Teacher Briefing scheduler aktif (15dk periyod, WP gönderim FLAG-GATED)")
        except Exception as e:
            logger.warning(f"  Briefing scheduler baslatilamadi: {e}")

    # ── 25.28: F4 Todo Assignment scheduler (30dk periyod, LEADER ONLY) ────
    _todo_task = None
    if _is_singleton_leader:
        try:
            from todo_assignment import todo_scheduler_loop
            _todo_task = asyncio.create_task(todo_scheduler_loop())
            logger.info("  📌  Todo Assignment scheduler aktif (30dk periyod, eskalasyon FLAG-GATED)")
        except Exception as e:
            logger.warning(f"  Todo scheduler baslatilamadi: {e}")

    # ── 25.43-BUG1-FIX (11 May, bot self-critique): Takeover hook ─────────
    # Multi-worker'da bu worker follower iken, eski leader düşerse takeover
    # eder ama singleton task'ler (nightly/session_keeper/scheduler/telafi/
    # briefing/todo) BAŞLATILMIYORDU → "manual restart gerekir" warning.
    # Şimdi callback ile otomatik başlat.
    try:
        from singleton_leader import set_takeover_callback

        async def _start_singleton_tasks_on_takeover():
            """Takeover sonrası eksik singleton task'leri başlat (idempotent)."""
            nonlocal _session_keeper_task, _scheduler_task, _html_task, _telafi_task
            nonlocal _briefing_task, _todo_task, _nightly_task
            logger.warning("  🚀  Takeover sonrası singleton task'ler başlatılıyor...")
            # Session keeper
            try:
                if not _session_keeper_task or _session_keeper_task.done():
                    from session_keeper import session_keeper_loop as _sk_loop
                    _session_keeper_task = asyncio.create_task(_sk_loop())
                    logger.info("  🔐  [takeover] Session Keeper aktif")
            except Exception as _e:
                logger.error(f"  [takeover] Session keeper fail: {_e}")
            # Scheduler + HTML
            try:
                if not _scheduler_task or _scheduler_task.done():
                    _scheduler_task = asyncio.create_task(_run_scheduled_tasks())
                    logger.info("  ⏰  [takeover] Scheduler aktif")
                if not _html_task or _html_task.done():
                    _html_task = asyncio.create_task(_run_conversation_html_updater())
                    logger.info("  📄  [takeover] HTML updater aktif")
            except Exception as _e:
                logger.error(f"  [takeover] Scheduler fail: {_e}")
            # Telafi
            try:
                if not _telafi_task or _telafi_task.done():
                    async def _telafi_loop_inner():
                        from frustration_telafi import check_and_send_telafi
                        while True:
                            await asyncio.sleep(1800)
                            try:
                                result = await check_and_send_telafi(send_wa_func=send_wa_message)
                                if result.get("sent", 0) > 0:
                                    logger.info(f"✨ [takeover] Telafi: {result['sent']} mesaj")
                            except Exception:
                                pass
                    _telafi_task = asyncio.create_task(_telafi_loop_inner())
                    logger.info("  ✨  [takeover] Telafi aktif")
            except Exception as _e:
                logger.error(f"  [takeover] Telafi fail: {_e}")
            # Briefing + Todo
            try:
                if not _briefing_task or _briefing_task.done():
                    from teacher_briefing import briefing_scheduler_loop
                    _briefing_task = asyncio.create_task(briefing_scheduler_loop())
                    logger.info("  📋  [takeover] Briefing aktif")
                if not _todo_task or _todo_task.done():
                    from todo_assignment import todo_scheduler_loop
                    _todo_task = asyncio.create_task(todo_scheduler_loop())
                    logger.info("  📌  [takeover] Todo aktif")
            except Exception as _e:
                logger.error(f"  [takeover] Briefing/Todo fail: {_e}")
            # Nightly
            try:
                if '_nightly_task' not in dir() or not _nightly_task or _nightly_task.done():
                    from precompute_nightly import nightly_scheduler_loop
                    _nightly_task = asyncio.create_task(nightly_scheduler_loop())
                    logger.info("  🌙  [takeover] Nightly aktif")
            except Exception as _e:
                logger.error(f"  [takeover] Nightly fail: {_e}")
            logger.warning("  ✅  Takeover singleton task'ler başlatıldı (otomatik)")

        set_takeover_callback(_start_singleton_tasks_on_takeover)
    except Exception as _hook_err:
        logger.warning(f"  Takeover callback register fail: {_hook_err}")

    yield  # Uygulama çalışıyor

    # ── Kapanış ────────────────────────────────────────────────────────────────
    # 25.44 (Neo direktif): Browser context singleton cleanup
    try:
        from eyotek_knowledge.eyotek_navigator import cleanup_navigator_singleton
        await cleanup_navigator_singleton()
        logger.info("  Browser singleton cleanup tamamlandı")
    except Exception as _nav_cleanup_err:
        logger.debug(f"Navigator singleton cleanup skip: {_nav_cleanup_err}")

    if _scheduler_task:
        _scheduler_task.cancel()
    if _html_task:
        _html_task.cancel()
    if _session_keeper_task:
        _session_keeper_task.cancel()
    if _telafi_task:
        _telafi_task.cancel()
    # 22.1n-neo: Nightly scheduler (precompute 03:00) de cancel
    try:
        if '_nightly_task' in locals() and _nightly_task:
            _nightly_task.cancel()
    except Exception:
        pass
    # 25.28: F1 + F4 scheduler cancel
    try:
        if '_briefing_task' in locals() and _briefing_task:
            _briefing_task.cancel()
    except Exception:
        pass
    try:
        if '_todo_task' in locals() and _todo_task:
            _todo_task.cancel()
    except Exception:
        pass

    # NOT: Ollama unload ZATEN fermat_start.py 'cikis' komutunda var (taskkill ollama.exe).
    # Bu yuzden bridge lifespan'da ayrica unload GEREKMEZ — mevcut davranisi KORUYORUZ.
    # Neo: "yeni ozellik ekleme, mevcudu koru" (21 Nisan 01:45)

    # DB pool kapat (Oturum 25.10b fix: db_pool modulu kullaniyoruz, _DB_POOL global yok)
    try:
        from db_pool import close_pool
        await close_pool()
    except Exception as _cp_e:
        logger.debug(f"DB pool kapatma hatasi (yok sayildi): {_cp_e}")
    logger.info("🛑  FermatAI Bridge kapanıyor — aktif session sayısı: "
                f"{len(_AGENT_SESSIONS)}")


_FASTAPI_DOCS_ENABLED = os.getenv("FASTAPI_DOCS", "false").lower() in ("1", "true", "yes")

# T3 (Oturum 25.9): Structured JSON logging — opt-in, default kapali
if os.getenv("JSON_LOGGING", "false").lower() in ("1", "true", "yes"):
    try:
        from json_logging import setup_json_logging
        setup_json_logging(min_level=os.getenv("JSON_LOG_LEVEL", "INFO"))
    except Exception as _jle:
        logger.warning(f"json_logging setup fail: {_jle}")

# ─────────────────────────────────────────────────────────────────────
# Oturum 25.38 — Sentry error tracking (production-grade)
# .env'de SENTRY_DSN tanımlıysa aktif olur. Free tier 5K event/ay yeterli.
# ─────────────────────────────────────────────────────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
_SENTRY_ENABLED = False
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                StarletteIntegration(transaction_style="endpoint"),
                AsyncioIntegration(),
            ],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=0.0,
            environment=os.getenv("SENTRY_ENV", "production"),
            release=os.getenv("SENTRY_RELEASE", "fermatai@25.38"),
            send_default_pii=False,  # KVKK — kullanıcı verisi gönderme
            before_send=lambda event, hint: (
                None if any(
                    skip in str(event.get("logger") or "")
                    for skip in ["uvicorn.access", "httpx", "asyncpg.compat"]
                )
                else event
            ),
        )
        _SENTRY_ENABLED = True
        logger.info(f"✓ Sentry aktif (env={os.getenv('SENTRY_ENV', 'production')})")
    except ImportError:
        logger.warning("sentry-sdk kurulu değil — pip install 'sentry-sdk[fastapi]'")
    except Exception as _se:
        logger.warning(f"Sentry init hata: {_se}")
else:
    logger.debug("SENTRY_DSN tanımsız — Sentry pasif")

app = FastAPI(
    title="FermatAI WhatsApp Bridge",
    version="1.0.0",
    lifespan=lifespan,
    # 22.1n-neo pentest hardening: /docs, /redoc, /openapi.json production'da kapali.
    # Sadece FASTAPI_DOCS=true env'i ayarlandiysa acik.
    docs_url="/docs" if _FASTAPI_DOCS_ENABLED else None,
    redoc_url="/redoc" if _FASTAPI_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _FASTAPI_DOCS_ENABLED else None,
)

# ── CORS — Wix iframe embed icin (fermategitimkurumlari.com) ──
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fermategitimkurumlari.com",
        "https://www.fermategitimkurumlari.com",
        "https://fermatvip.com",
        "https://www.fermatvip.com",
        # Wix editor/preview alt domain'leri
        "https://editor.wix.com",
        "https://*.wixsite.com",
        "https://*.editorx.com",
    ],
    allow_origin_regex=r"https://.*\.(wixsite|wix|filesusr)\.com",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Web Chat Router ──
try:
    from web_chat import router as _web_chat_router
    app.include_router(_web_chat_router)
except Exception as _wcerr:
    import logging as _lg
    _lg.warning(f"web_chat router yuklenemedi: {_wcerr}")

# ── Dashboard API Router (Oturum 25.9) ──
try:
    from dashboard_api import router as _dashboard_router
    app.include_router(_dashboard_router)
except Exception as _dberr:
    import logging as _lg
    _lg.warning(f"dashboard_api router yuklenemedi: {_dberr}")

# ── Öğrenci Günlük Takip Router (Oturum 25.12) ──
try:
    from student_daily_api import router as _student_daily_router
    app.include_router(_student_daily_router)
except Exception as _sderr:
    import logging as _lg
    _lg.warning(f"student_daily_api router yuklenemedi: {_sderr}")

# ── Render Endpoint Router (Oturum 25.31, Neo) — bot HTML üretirse kalıcı link ──
try:
    from render_endpoint import router as _render_router
    app.include_router(_render_router)
except Exception as _rerr:
    import logging as _lg
    _lg.warning(f"render_endpoint router yuklenemedi: {_rerr}")

# ── 25.46+ (Neo 17 May): Topluluk sohbet (QuitNow tarzı) ──
try:
    from topluluk_endpoint import router as _topluluk_router
    app.include_router(_topluluk_router)
except Exception as _terr:
    import logging as _lg
    _lg.warning(f"topluluk router yuklenemedi: {_terr}")

# ── Static endpoints — audio (TTS) + pdf + anki + img (Oturum 25.34/25.38/25.40) ──
try:
    from fastapi import FastAPI as _F
    from fastapi.staticfiles import StaticFiles as _SF
    from pathlib import Path as _P
    _audio_dir = _P("/opt/fermatai/eyotek_agent/logs/audio")
    _pdf_dir = _P("/opt/fermatai/eyotek_agent/logs/pdfs")
    _anki_dir = _P(__file__).parent / "static" / "anki"   # Oturum 25.38
    _img_dir = _P(__file__).parent / "static" / "img"     # Oturum 25.40 (PWA iconlar)
    _games_dir = _P(__file__).parent / "static" / "games"  # 25.46+ (Neo 17 May: chess MVP)
    _audio_dir.mkdir(parents=True, exist_ok=True)
    _pdf_dir.mkdir(parents=True, exist_ok=True)
    _anki_dir.mkdir(parents=True, exist_ok=True)
    _img_dir.mkdir(parents=True, exist_ok=True)
    _games_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/audio", _SF(directory=str(_audio_dir)), name="audio")
    app.mount("/pdfs", _SF(directory=str(_pdf_dir)), name="pdfs")
    app.mount("/static/anki", _SF(directory=str(_anki_dir)), name="anki")
    app.mount("/static/img", _SF(directory=str(_img_dir)), name="pwa_img")
    app.mount("/static/games", _SF(directory=str(_games_dir)), name="games")
except Exception as _serr:
    import logging as _lg
    _lg.warning(f"static mount hata: {_serr}")


# ── 25.46+ (Neo 17 May): /chess shortcut → /static/games/chess.html ──
@app.get("/chess", include_in_schema=False)
async def chess_shortcut(name: str = "", v: str = ""):
    """FermatAI Satrancı kisa URL. Minimax depth=3, no-cache (her zaman tazeleyecek)."""
    from fastapi.responses import FileResponse, Response
    chess_path = _P(__file__).parent / "static" / "games" / "chess.html"
    if not chess_path.exists():
        raise HTTPException(404, "chess.html bulunamadi")
    # 25.46+ no-cache: minigame surekli geliyor, browser cache eskiyebilir
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return FileResponse(path=str(chess_path), media_type="text/html", headers=headers)


# ── Oturum 25.40 (Neo PWA): Service Worker ROOT scope serve ──
# SW /service-worker.js root'tan serve edilmeli ki scope='/' alabilsin
# (Aksi takdirde /chat altında scope sınırlı kalır → /render/ cache edemez)
@app.get("/service-worker.js", include_in_schema=False)
async def root_service_worker():
    """Service Worker — root scope (cache /chat + /render + /static)."""
    from fastapi.responses import FileResponse
    sw_path = _P(__file__).parent / "static" / "service-worker.js"
    if not sw_path.exists():
        raise HTTPException(404, "service-worker.js bulunamadı")
    response = FileResponse(path=str(sw_path), media_type="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/manifest.json", include_in_schema=False)
async def root_manifest():
    """PWA Manifest — root scope için duplicate (PWA standard)."""
    from web_chat import pwa_manifest
    return await pwa_manifest()


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Favicon — fallback PNG."""
    from fastapi.responses import FileResponse
    fav = _P(__file__).parent / "static" / "img" / "favicon.png"
    if fav.exists():
        return FileResponse(path=str(fav), media_type="image/png")
    raise HTTPException(404)

# ── Renderer Test Page (Oturum 25.35) — tum 22 renderer ornek data ile ──
@app.get("/render-test", include_in_schema=False)
async def render_test_page():
    """Tüm renderer'ları örnek data ile gösteren test sayfası."""
    from fastapi.responses import HTMLResponse
    from pathlib import Path as _P
    chat_html = _P("/opt/fermatai/eyotek_agent/web_chat_ui.html").read_text(encoding="utf-8")
    # head ve script CDN'leri olduğu gibi al
    import re
    head_match = re.search(r"<head>([\s\S]*?)</head>", chat_html)
    head_content = head_match.group(1) if head_match else ""
    # Tüm renderer örnek data
    test_md = """
# 🧪 FermatAI Renderer Test Sayfası

22 renderer + animasyonlar canlı test.

---
## 1. ```sim — p5.js (sinüs dalgası)
```sim
let t=0;
function setup(){createCanvas(500,250);}
function draw(){background(245);t+=0.05;stroke(199,111,62);strokeWeight(2);noFill();beginShape();for(let x=0;x<width;x++){vertex(x,height/2+sin(x*0.04+t)*40);}endShape();}
```

---
## 2. ```3d — Three.js DNA helix
```3d
{"scene":"dna_helix","title":"DNA Çift Sarmal"}
```

---
## 3. ```formula — KaTeX adım adım
```formula
step: $E = h\\nu$
step: $E_k = h\\nu - \\phi$
step: $\\nu_0 = \\phi/h$
```

---
## 4. ```calc — Slider hesaplama
```calc
frekans: 0..20 [Hz] (varsayilan 10)
genlik: 0..5 (varsayilan 2)
→ omega = 2 * 3.14159 * frekans
```

---
## 5. ```chart — Chart.js line
```chart
{"type":"line","data":{"labels":["TYT-1","TYT-2","TYT-3","TYT-4"],"datasets":[{"label":"Net","data":[68,72,75,82],"borderColor":"#C76F3E"}]}}
```

---
## 6. ```radar — Yetkinlik spider
```radar
{"title":"TYT Profili","labels":["Türkçe","Mat","Fen","Sosyal"],"datasets":[{"label":"Sen","data":[28,32,18,22]},{"label":"Ortalama","data":[24,26,20,23]}]}
```

---
## 7. ```heatmap — Konu × hafta
```heatmap
{"title":"Fizik Hata Yoğunluğu","x":["Hafta 1","Hafta 2","Hafta 3"],"y":["Kuvvet","Enerji","Manyetizma"],"values":[[2,1,3],[5,4,2],[8,7,9]]}
```

---
## 8. ```karne — Renk kodlu matris
```karne
{"title":"Karne","rows":[{"ders":"Fizik","konular":[{"ad":"Kuvvet","puan":85,"renk":"yesil"},{"ad":"Manyetizma","puan":42,"renk":"sari"},{"ad":"Modern","puan":18,"renk":"kirmizi"}]}]}
```

---
## 9. ```gauge — Yüzdelik
```gauge
{"title":"YKS Hedef","value":78,"min":0,"max":100,"unit":"%","label":"Mevcut"}
```

---
## 10. ```timeline — Zaman çizgisi
```timeline
{"title":"Deneme Tarihçen","events":[{"tarih":"2026-01-15","baslik":"TYT-1","aciklama":"Net: 68","tip":"sinav"},{"tarih":"2026-02-20","baslik":"TYT-2","aciklama":"Net: 72","tip":"sinav"},{"tarih":"2026-03-25","baslik":"TYT-3","aciklama":"Net: 75","tip":"sinav"}]}
```

---
## 11. ```progress — Donut tamamlanma
```progress
{"title":"Müfredat","items":[{"label":"Fizik","value":68,"color":"#C76F3E"},{"label":"Mat","value":82,"color":"#6B8E7F"},{"label":"Kimya","value":45,"color":"#A78BFA"}]}
```

---
## 12. ```compare — Yan yana
```compare
{"title":"TYT-2 vs TYT-3","cards":[{"baslik":"TYT-2","puan":420,"net":72,"detay":["Mat: 28","Fen: 18"]},{"baslik":"TYT-3","puan":445,"net":75,"detay":["Mat: 30 (+2)","Fen: 19 (+1)"]}]}
```

---
## 13. ```desmos — Matematik grafik
```desmos
{"title":"Parabol","expressions":[{"id":"e1","latex":"y=x^2","color":"#C76F3E"}]}
```

---
## 14. ```geogebra — Geometri 3D
```geogebra
{"type":"3d","title":"3D Koordinat"}
```

---
## 15. ```plot3d — Plotly 3D
```plot3d
{"title":"3D Surface","data":[{"type":"surface","z":[[1,2,3,4],[2,4,6,8],[3,6,9,12],[4,8,12,16]],"colorscale":"Viridis"}]}
```

---
## 16. ```mermaid — Akış
```mermaid
graph LR
  A[Foton] --> B{Enerji yeterli?}
  B -->|Evet| C[Elektron firlar]
  B -->|Hayir| D[Etki yok]
```

---
## 17. ```vr — A-Frame atom
```vr
{"scene":"atom","title":"Hidrojen"}
```

---
## 18. ```mol3d — Kafein 3D (PubChem)
```mol3d
{"cid":2519,"title":"Kafein","style":"stick"}
```

---
## 19. ```sound — Tone.js frekans
```sound
{"title":"440 Hz - La","frequency":440,"min":100,"max":2000,"wave":"sine"}
```

---
## 20. ```element — Demir
```element
{"symbol":"Fe","title":"Demir","note":"Hemoglobin temeli"}
```

---
## 21. ```excalidraw — Çizim
```excalidraw
{"title":"Boş çizim tahtası"}
```

---
## 22. ```codeout — Python output
```codeout
{"title":"factorial(10)","code":"import math\\nprint(math.factorial(10))","stdout":"3628800","success":true}
```

---
## 23. ```steps — Step-by-step solver
```steps
{"title":"x²+5x+6=0 köklerini bul","steps":[
  {"title":"Çarpanlara ayır","body":"x²+5x+6 = (x+2)(x+3)","reason":"Sabit terim 6 = 2×3 ve 2+3 = 5 = ortadaki katsayı"},
  {"title":"Sıfıra eşitle","body":"(x+2)·(x+3) = 0\\n\\nÇarpım sıfır → en az biri sıfır"},
  {"title":"Kökleri yaz","body":"x+2=0 → x=-2\\nx+3=0 → x=-3"}
],"conclusion":"x ∈ {-2, -3}"}
```

---
## 24. ```kgraph — Knowledge Graph (D3 force layout)
```kgraph
{"title":"Matematik Konu Haritası","nodes":[
  {"id":"limit","label":"Limit","ders":"Mat","mastery":0.4,"size":22},
  {"id":"turev","label":"Türev","ders":"Mat","mastery":0.6,"size":18},
  {"id":"integral","label":"İntegral","ders":"Mat","mastery":0.3,"size":24},
  {"id":"fonk","label":"Fonksiyonlar","ders":"Mat","mastery":0.85,"size":14},
  {"id":"trig","label":"Trigonometri","ders":"Mat","mastery":0.5,"size":17}
],"links":[
  {"source":"limit","target":"turev","weight":0.9},
  {"source":"turev","target":"integral","weight":0.95},
  {"source":"fonk","target":"limit","weight":0.7},
  {"source":"trig","target":"turev","weight":0.6}
],"stats":{"weakest_3":["İntegral","Limit","Trigonometri"]}}
```

---
## 25. ```quiz — Interactive quiz (multi-choice + feedback)
```quiz
{"title":"Limit Hızlı Test","questions":[
  {"stem":"lim(x→0) sin(x)/x = ?","choices":["0","1","∞","tanımsız"],"correct":1,
   "explanation":"Standart limit (L'Hôpital veya Taylor): sin(x)/x → 1"},
  {"stem":"lim(x→2) (x²-4)/(x-2) = ?","choices":["0","2","4","∞"],"correct":2,
   "explanation":"(x²-4)=(x-2)(x+2) → sadeleşir, x+2 yerine 2 koy → 4"}
]}
```

---
## 26. ```compare2 — Concept Comparison Matrix
```compare2
{"title":"Mitoz vs Mayoz","left":{"label":"Mitoz","summary":"Vücut hücreleri"},"right":{"label":"Mayoz","summary":"Üreme hücreleri"},
"rows":[
  {"aspect":"Hücre sayısı","left":"2","right":"4","highlight":true},
  {"aspect":"Kromozom","left":"2n (diploid)","right":"n (haploid)"},
  {"aspect":"Crossing-over","left":"Yok","right":"Var (Profaz I)","highlight":true},
  {"aspect":"Çeşitlilik","left":"Yok (klon)","right":"Yüksek"}
],"takeaway":"Mayoz çeşitlilik üretir, mitoz büyütür"}
```

---
## 27. ```recall — Active Recall hatırlatma
```recall
{"konu":"Fotoelektrik Olayı","ders":"Fizik",
"summary":"Foton enerjisi E = hν, eşik frekansı altında elektron çıkmaz",
"action":"Şimdi sen anlat — fotoelektrik olayı kısaca nasıl çalışır? Eşik frekansı ne demek?",
"interval_hours":24}
```

---
## 28. ```compound — 2-3 renderer tek kart
```compound
{"title":"Newton 2. Yasa Tam Paket","panels":[
  {"type":"formula","label":"Yasa","data":{"body":"$F = m \\\\cdot a$"}},
  {"type":"karne","label":"Senin Durumun","data":{"title":"Mekanik","konular":[{"konu":"Newton","skor":65,"hedef":80}]}}
],"note":"Formül + senin durumun = compound learning"}
```

---
## ✅ Eğer hepsi düzgün render ediyorsa: **28/28 renderer çalışıyor.**
"""
    test_md_safe = test_md.replace("</script>", "<\\/script>").replace("`", "\\`")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="tr"><head>{head_content}</head>
<body>
<div class="chat-wrap active" style="height:100vh; overflow-y:auto;">
  <div class="chat-messages" id="messages" style="max-width: 900px; margin: 0 auto; padding: 24px 16px;">
    <div class="msg bot" id="testbot"></div>
  </div>
</div>
<script>
const TEST_MD = `{test_md_safe}`;
window.addEventListener("DOMContentLoaded", () => {{
  setTimeout(() => {{
    const el = document.getElementById("testbot");
    if (typeof formatMsg === "function") {{
      el.innerHTML = formatMsg(TEST_MD);
      if (typeof rerenderAllVisuals === "function") {{
        rerenderAllVisuals(el);
      }}
      if (typeof rerenderMath === "function") {{
        try {{ rerenderMath(el); }} catch(e) {{ console.warn(e); }}
      }}
    }} else {{
      el.textContent = "formatMsg fonksiyonu yuklenemedi";
    }}
  }}, 500);
}});
</script>
</body></html>""")

# 22.1n-neo Paket A: HybridDict wrapper — memory mode davranisi aynen, Redis aktif
# olunca (REDIS_URL set) otomatik multi-worker shared state.
# _AGENT_SESSIONS FermatCoreAgent INSTANCE tuttugu icin serialize edilemez → memory only.
_AGENT_SESSIONS: dict[str, object] = {}  # FermatCoreAgent instance — serialize yok
_PROCESSED_MSG_IDS: set[str] = set()      # set — memory only
_PENDING_FOLLOWUP: dict[str, str] = {}    # kisa string, memory (hybrid gerekli degil)
_PENDING_SPLIT: dict[str, dict] = {}      # dict meta, memory (hybrid gerekli degil)

# ── Rate Limiting + Flood Koruma ─────────────────────────────────────────────
import time as _time
from hybrid_state import HybridDict, HybridPhoneLocks, is_redis_mode

_CAPACITY_WINDOW = 300       # 5 dakikalık pencere
_CAPACITY_MAX = 30           # kayıtlı kullanıcı: 5dk'da 30 birim (rahat diyalog)
_CAPACITY_MAX_UNKNOWN = 15   # kayıtsız: 5dk'da 15 birim
_FLOOD_THRESHOLD = 50        # 5dk'da 50+ birim = flood
_FLOOD_BAN_DURATION = 3600   # 1 saat ban

# 22.1n-neo Paket A: HybridDict — Redis varsa dual-write, yoksa eski davranis
_CAPACITY_COUNTS = HybridDict("cap:", ttl_default=_CAPACITY_WINDOW * 2)
_TEMP_BANS = HybridDict("ban:", ttl_default=_FLOOD_BAN_DURATION)

# ── Medya Kontrol ────────────────────────────────────────────────────────────
_PHOTO_DAILY_LIMIT = 5   # ogrenci basina gunluk foto limiti (Neo direktif 9 May, 10 → 5 maliyet kontrolu)
_PHOTO_COUNTS = HybridDict("photo:", ttl_default=86400)  # {phone: {"date": "2026-04-08", "count": 5}}
VIDEO_ENABLED = False  # Video KAPALI — gereksiz islem gucu


async def get_photo_usage(phone: str, soz_no=None) -> tuple[int, int, int]:
    """25.50 (Opus 4.8 review): foto kullanım TEK KAYNAK — (kullanilan, limit, kalan).

    ÖNCEDEN: enforcement _PHOTO_COUNTS (HybridDict, in-memory) kullanıyordu ama
    fast_responses'taki bilgi gösterimi AYRI bir DB COUNT sorgusu yapıyordu +
    except:pass. İki kaynak diverge ediyordu: DB hatası → 'kalan 5' gösterir ama
    enforcement 0 der → öğrenci foto atar, bloklanır (yanıltıcı UX). Bu helper
    enforcement ile AYNI kaynaktan okur → tutarlılık + fail-safe garanti.
    """
    from datetime import date as _date
    today = _date.today().isoformat()
    pc = _PHOTO_COUNTS.get(phone, {"date": "", "count": 0})
    kullanilan = pc.get("count", 0) if pc.get("date") == today else 0
    limit = _PHOTO_DAILY_LIMIT
    if soz_no:
        try:
            from foto_solver_v2 import get_dynamic_photo_limit
            limit = await get_dynamic_photo_limit(soz_no, _PHOTO_DAILY_LIMIT)
        except Exception as _e:
            logger.debug(f"[FOTO_USAGE] dinamik limit alınamadı, base={_PHOTO_DAILY_LIMIT}: {_e}")
    return kullanilan, limit, max(0, limit - kullanilan)

# Neo admin numarasi (Mimar)
# NEO — Sistem Efendisi. Bu numara ASLA değiştirilemez, paylaşılamaz, devre dışı bırakılamaz.
# Tüm admin komutları, onaylar ve sistem kontrolü sadece bu numaradan çalışır.
# İkinci bir admin ASLA oluşturulamaz — bu güvenlik kuralı kod seviyesinde zorunludur.
NEO_PHONE = "905051256802"  # Zeki Göksal — tek ve değişmez


def _check_rate_limit(phone: str, is_registered: bool = True, msg_len: int = 0) -> bool:
    """Kapasite bazlı rate limiting. Kısa mesajlar ucuz, Claude çağrıları pahalı.

    Oturum 25.40 (Neo direktif): Admin (Neo) için rate limit BYPASS — yatırım
    yapılmış altyapı tam kapasite kullanılabilsin, dev/test sınırsız.
    """
    # 25.40: Admin telefonu (Neo) için sınırsız
    NEO_PHONE = "905051256802"
    if phone == NEO_PHONE:
        return True  # Neo sınırsız

    now = _time.time()

    # Temp ban kontrolu
    if phone in _TEMP_BANS:
        if now < _TEMP_BANS[phone]:
            return False
        del _TEMP_BANS[phone]

    # Mevcut kapasiteyi hesapla (5dk pencere)
    entries = _CAPACITY_COUNTS.get(phone, [])
    entries = [(t, u) for t, u in entries if now - t < _CAPACITY_WINDOW]

    total_units = sum(u for _, u in entries)

    # Flood algılama
    if total_units >= _FLOOD_THRESHOLD:
        _TEMP_BANS[phone] = now + _FLOOD_BAN_DURATION
        logger.warning(f"FLOOD ALGILANDI: {phone} — 1 saat banlandi! ({total_units} birim)")
        return False

    # Kapasite kontrolü
    max_cap = _CAPACITY_MAX if is_registered else _CAPACITY_MAX_UNKNOWN
    if total_units >= max_cap:
        return False

    # Bu mesajın birim maliyeti (mesaj uzunluğuna göre)
    if msg_len < 50:
        units = 1      # kısa mesaj — "merhaba", "evet"
    elif msg_len < 200:
        units = 2      # orta mesaj
    else:
        units = 3      # uzun mesaj

    entries.append((now, units))
    _CAPACITY_COUNTS[phone] = entries
    return True


def _add_capacity_cost(phone: str, source: str):
    """Yanıt kaynağına göre ek kapasite maliyeti ekle. Claude pahalı, fast/local ucuz."""
    now = _time.time()
    entries = _CAPACITY_COUNTS.get(phone, [])
    if source == "claude":
        entries.append((now, 5))   # Claude API çağrısı = 5 birim
    elif source == "ollama":
        entries.append((now, 1))   # Ollama = 1 birim
    # fast_response = 0 birim (ek maliyet yok)
    _CAPACITY_COUNTS[phone] = entries


# 22.1n-neo Fikir 4: Smart Rate Limit — per-phone Claude burst koruma
# Damla orneği: 9 istek 75s'ye dayandı. Aynı ogrenci 60 saniyede N+ Claude tetiklediyse,
# son gelen mesaj Claude'a gonderilmeden "Onceki isteklerin hala isleniyor" yaniti.
# 22.1n-neo Paket A: HybridDict — Redis varsa dual-write
_CLAUDE_CALLS = HybridDict("claude_burst:", ttl_default=300)  # {phone: [timestamp, ...]}
_CLAUDE_BURST_WINDOW = 60            # 60 saniye
_CLAUDE_BURST_MAX = 3                # Neo haric: 60sn icinde max 3 Claude tetigi


def track_claude_call(phone: str) -> None:
    """Claude cagrilarini izle — burst detection icin."""
    now = _time.time()
    entries = _CLAUDE_CALLS.get(phone, [])
    entries = [t for t in entries if now - t < _CLAUDE_BURST_WINDOW]
    entries.append(now)
    _CLAUDE_CALLS[phone] = entries


def is_claude_burst(phone: str) -> bool:
    """Bu phone son 60sn'de 3+ Claude cagrisinda mi?

    Neo haric — Neo admin, sinirsiz.
    Burst ise True: bir sonraki Claude cagrisi IPTAL edilsin.
    """
    if phone == NEO_PHONE:
        return False  # Neo rate limit'ten muaf
    now = _time.time()
    entries = _CLAUDE_CALLS.get(phone, [])
    active = [t for t in entries if now - t < _CLAUDE_BURST_WINDOW]
    return len(active) >= _CLAUDE_BURST_MAX


def claude_burst_message(phone: str) -> str:
    """Burst algilandığinda döndürülecek yanıt (Claude'a gitmez, direkt)."""
    entries = _CLAUDE_CALLS.get(phone, [])
    wait_sn = _CLAUDE_BURST_WINDOW if not entries else max(
        10, int(_CLAUDE_BURST_WINDOW - (_time.time() - entries[0]))
    )
    return (
        f"⏳ Önceki isteklerin üzerinde hâlâ çalışıyorum, biraz sabır 🙏\n\n"
        f"Yoğun analiz zinciri açık — *~{wait_sn} saniye* içinde yanıt hazır olacak.\n"
        f"_Yeni soru gelirse sıraya alırım, endişelenme._ ✨"
    )


async def _is_phone_registered(phone: str) -> dict | None:
    """Telefon numarasi ACL'de kayitli mi? Kayitliysa profil don. Veli kontrolü dahil."""
    try:
        from fermat_core_agent import _get_caller_profile
        profile = await _get_caller_profile(phone)
        if profile.get("role") not in ("unknown", "guest"):
            return profile
    except Exception:
        pass

    # ACL'de yoksa — veli mi kontrol et
    # FEATURE FLAG: Veli modülü hazır ama AKTİF DEĞİL — Neo "veli aktif" diyene kadar
    VELI_MODULE_ACTIVE = False  # Neo tarafından aktif edilecek
    if VELI_MODULE_ACTIVE:
        try:
            from veli_module import find_child_by_parent_phone, register_parent
            child = await find_child_by_parent_phone(phone)
            if child:
                await register_parent(phone, child)
                return {
                    "role": "veli",
                    "full_name": f"Veli ({child['full_name']})",
                    "phone": phone,
                    "child_soz_no": child['soz_no'],
                    "child_name": child['full_name'],
                    "child_class": child['class_name'],
                }
        except Exception as e:
            logger.debug(f"Veli kontrol hatası: {e}")

    return None


# Gecici bloklar (in-memory, 1 saatlik) — hack/spam tespiti sonrasi
_TEMP_BLOCKS: dict[str, float] = {}  # {phone: unix_ts_until}


def temp_block_phone(phone: str, minutes: int = 60) -> None:
    """Numarayi gecici blokla (default 1 saat)."""
    import time as _time
    _TEMP_BLOCKS[phone] = _time.time() + (minutes * 60)
    logger.warning(f"🚫 TEMP BLOCK: {phone} — {minutes}dk")


def is_temp_blocked(phone: str) -> bool:
    """Gecici blok kontrolu + expired olanlari temizle."""
    import time as _time
    now = _time.time()
    expiry = _TEMP_BLOCKS.get(phone)
    if not expiry:
        return False
    if now >= expiry:
        _TEMP_BLOCKS.pop(phone, None)
        return False
    return True


async def _is_phone_blocked(phone: str) -> bool:
    """Numara bloklu mu? (kalici veya gecici)"""
    # Gecici blok kontrolu once (daha hizli)
    if is_temp_blocked(phone):
        return True
    try:
        row = await db_fetchval("SELECT 1 FROM blocked_numbers WHERE phone=$1", phone)
        return row is not None
    except Exception:
        return False


# ── Token Otomatik Yenileme ──────────────────────────────────────────────────

async def _refresh_wa_token() -> str | None:
    """WA Access Token expire olduğunda otomatik yenile (Graph API long-lived token)."""
    global WA_ACCESS_TOKEN
    app_id = os.getenv("FB_APP_ID", "")
    app_secret = os.getenv("FB_APP_SECRET", "")
    if not app_id or not app_secret:
        logger.error("FB_APP_ID veya FB_APP_SECRET .env'de yok — token yenileyemiyorum")
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{GRAPH_BASE}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "fb_exchange_token": WA_ACCESS_TOKEN,
                }
            )
            data = r.json()
            new_token = data.get("access_token")
            if new_token:
                WA_ACCESS_TOKEN = new_token
                # .env dosyasını güncelle
                env_path = Path(__file__).parent / ".env"
                env_content = env_path.read_text(encoding="utf-8")
                import re as _re
                env_content = _re.sub(
                    r"WA_ACCESS_TOKEN=.*",
                    f"WA_ACCESS_TOKEN={new_token}",
                    env_content
                )
                env_path.write_text(env_content, encoding="utf-8")
                logger.success(f"✅ WA Token otomatik yenilendi! (yeni uzunluk: {len(new_token)})")
                return new_token
            else:
                logger.error(f"Token yenileme başarısız: {data}")
                return None
    except Exception as e:
        logger.error(f"Token yenileme hatası: {e}")
        return None


# ── WhatsApp API Yardımcıları ─────────────────────────────────────────────────

# Oturum 23 meeting bug fix: Duplicate response guard
# Zehra vakası — bot aynı "Dur bir saniye Zehra..." mesajını 8 dk içinde 2 kez gönderdi.
# In-memory cache, phone → son 10 hash+ts. Son 5 dk'da aynı hash varsa SKIP.
import hashlib as _hashlib
_DUP_CACHE: dict[str, list[tuple[str, float]]] = {}


def _is_duplicate_send(to: str, text: str, window_seconds: int = 300) -> bool:
    """Son 5 dk içinde aynı phone'a aynı içerik gönderildi mi?

    Her phone için son 10 gönderimin hash+timestamp'i tutulur. Araya farklı
    mesaj girse bile eski aynı içerik window içindeyse BLOK.
    """
    import time as _t
    if not to or not text:
        return False
    clean_to = (to or "").replace("+", "").strip()
    h = _hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
    now = _t.time()
    history = _DUP_CACHE.get(clean_to, [])
    # Window dışındakileri temizle
    history = [(hh, ts) for hh, ts in history if (now - ts) < window_seconds]
    # Herhangi bir eşleşme?
    for old_hash, old_ts in history:
        if old_hash == h:
            logger.warning(f"🔁 DUPLICATE RESPONSE BLOKLANDI: phone=...{clean_to[-4:]} "
                          f"age={int(now - old_ts)}s content_len={len(text)}")
            return True
    # Yeni entry ekle (max 10 tut)
    history.append((h, now))
    _DUP_CACHE[clean_to] = history[-10:]
    # Cache boyut kontrolü — max 200 phone
    if len(_DUP_CACHE) > 200:
        oldest = sorted(_DUP_CACHE.items(), key=lambda x: x[1][-1][1] if x[1] else 0)[:50]
        for k, _ in oldest:
            _DUP_CACHE.pop(k, None)
    return False


async def send_wa_message(to: str, text: str, *, _outreach: bool = False, _reason: str = "") -> bool:
    """WhatsApp text mesajı gönder.

    22.1n-kural1 (KRITIK — Neo direkt talimat 20/04):
    Proaktif mesaj (_outreach=True) icin OUTREACH_ENABLED=true olmali.
    False (default) iken Neo (admin) HARIC hicbir kullaniciya mesaj gitmez.
    Bloklanan mesajlar outreach_pending tablosuna dusululur — Neo gozden gecirir.

    Reply (kullaniciya cevap) guard'a takilmaz, cunku _outreach=False default.

    Oturum 23 meeting fix: Duplicate guard — aynı içerik 5 dk içinde tekrar
    gitmez (Zehra vakası).
    """
    if _outreach and not _outreach_allowed(to):
        return await _block_outreach(to, text, _reason)

    # 25.44 (Neo direktif 12 May): ```chart {json}``` blokları → QuickChart image URL
    # Text'ten chart bloklarını çıkar, sonra her birini image olarak ekstra mesaj gönder.
    _chart_image_urls = []
    try:
        from chart_url_helper import process_text_for_chart_images
        text, _chart_image_urls = await process_text_for_chart_images(text)
    except Exception as _chart_err:
        logger.debug(f"chart→image skip: {_chart_err}")

    # Duplicate guard — Neo'yu etkilemez (admin zaten kısa uyarılar gönderir, nadir dup)
    if _is_duplicate_send(to, text):
        return False  # Sessizce bloke — log zaten düştü

    if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
        logger.warning("WA_ACCESS_TOKEN veya WA_PHONE_NUMBER_ID tanımlı değil — konsola yazılıyor.")
        logger.info(f"📤 [{to}]: {text}")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text[:4096]},
    }
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                WA_API_URL,
                headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}",
                         "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code == 200:
                logger.success(f"✅ WA mesaj gönderildi → {to}")
                # 25.44: chart bloklarından üretilen image URL'leri ardından gönder
                for _chart_url in _chart_image_urls:
                    try:
                        await send_wa_image(to, _chart_url, caption="📊")
                    except Exception as _ce:
                        logger.debug(f"chart image send skip: {_ce}")
                return True
            elif r.status_code == 401:
                logger.warning(f"⚠️ WA Token expired! Otomatik yenileme deneniyor...")
                new_token = await _refresh_wa_token()
                if new_token:
                    # Yeni token ile tekrar dene
                    r2 = await client.post(
                        WA_API_URL,
                        headers={"Authorization": f"Bearer {new_token}",
                                 "Content-Type": "application/json"},
                        json=payload,
                    )
                    if r2.status_code == 200:
                        logger.success(f"✅ Token yenilendi ve mesaj gönderildi → {to}")
                        return True
                logger.error(f"WA Token yenileme başarısız: {r.text[:200]}")
                return False
            else:
                logger.error(f"WA API hata {r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"WA gönderme hatası: {e}")
            return False


async def send_wa_image(to: str, image_url: str, caption: str = "", *, _outreach: bool = False, _reason: str = "") -> bool:
    """WhatsApp image mesajı gönder (URL ile).

    22.1n-kural1: _outreach=True ise OUTREACH_ENABLED gerekli (Neo onay).
    """
    if _outreach and not _outreach_allowed(to):
        return await _block_outreach(to, f"[IMAGE] {caption or image_url[:80]}", _reason)

    if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
        logger.warning("WA token/phone_id yok — image gönderilemedi.")
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption[:1024]},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(
                WA_API_URL,
                headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}",
                         "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code == 200:
                logger.success(f"✅ WA image gönderildi → {to}")
                return True
            elif r.status_code == 401:
                new_token = await _refresh_wa_token()
                if new_token:
                    r2 = await client.post(
                        WA_API_URL,
                        headers={"Authorization": f"Bearer {new_token}",
                                 "Content-Type": "application/json"},
                        json=payload,
                    )
                    if r2.status_code == 200:
                        logger.success(f"✅ Token yenilendi, image gönderildi → {to}")
                        return True
                logger.error(f"WA image token hatası: {r.text[:200]}")
                return False
            else:
                logger.error(f"WA image API hata {r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            logger.error(f"WA image gönderme hatası: {e}")
            return False


async def send_wa_document(to: str, file_path: str, caption: str = "", filename: str = None) -> bool:
    """WhatsApp document mesajı gönder (yerel PDF dosyasından).

    Önce media upload endpoint'ine yükler (media_id alır),
    sonra messages endpoint'ine media_id ile gönderir.
    """
    if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
        logger.warning("WA token/phone_id yok — document gönderilemedi.")
        return False
    if not os.path.exists(file_path):
        logger.error(f"Document dosyasi yok: {file_path}")
        return False
    if not filename:
        filename = os.path.basename(file_path)

    media_url = f"{GRAPH_BASE}/{WA_PHONE_NUMBER_ID}/media"

    async def _upload(token: str) -> str | None:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, 'rb') as f:
                files = {
                    'file': (filename, f, 'application/pdf'),
                }
                data = {
                    'messaging_product': 'whatsapp',
                    'type': 'application/pdf',
                }
                r = await client.post(
                    media_url,
                    headers={"Authorization": f"Bearer {token}"},
                    data=data,
                    files=files,
                )
                if r.status_code == 200:
                    return r.json().get('id')
                logger.error(f"WA media upload hata {r.status_code}: {r.text[:300]}")
                return None

    # 1. Media upload
    media_id = await _upload(WA_ACCESS_TOKEN)
    if not media_id:
        # Token yenileme dene
        new_token = await _refresh_wa_token()
        if new_token:
            media_id = await _upload(new_token)
    if not media_id:
        return False

    # 2. Send document message
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            "caption": caption[:1024],
        },
    }
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(
                WA_API_URL,
                headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}",
                         "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code == 200:
                logger.success(f"✅ WA document gönderildi → {to}: {filename}")
                return True
            else:
                logger.error(f"WA document API hata {r.status_code}: {r.text[:300]}")
                return False
        except Exception as e:
            logger.error(f"WA document gönderme hatası: {e}")
            return False


def kaynak_to_cdn_url(kaynak: str) -> str | None:
    """RAG kaynak stringini CDN URL'e çevir.

    Örnek: 'OGM Vision: 68b4eb6deb07 s.120' → CDN URL
    """
    import re
    from ogm_vision_importer import KITAPLAR
    CDN = "https://ogm-small-cdn.eba.gov.tr/ogm-test-images"

    # Format 1: "OGM Vision: 68b4eb6deb07 s.120"
    m = re.search(r'OGM Vision:\s*(\w+)\s*s\.(\d+)', kaynak or "")
    if m:
        kid_prefix = m.group(1)
        page_num = m.group(2)
        for kitap in KITAPLAR.values():
            if kitap["id"].startswith(kid_prefix):
                return f"{CDN}/{kitap['id']}/pages/{page_num}.jpg"

    # Format 2: "OGM Vision: kitap 68b4eb6d sayfa 10"
    m2 = re.search(r'kitap\s+(\w+)\s+sayfa\s+(\d+)', kaynak or "")
    if m2:
        kid_short = m2.group(1)
        page_num2 = m2.group(2)
        for kitap in KITAPLAR.values():
            if kitap["id"][:len(kid_short)] == kid_short:
                return f"{CDN}/{kitap['id']}/pages/{page_num2}.jpg"

    return None


async def send_wa_typing(to: str) -> None:
    """Yazıyor... göstergesi gönder (opsiyonel)."""
    if not WA_ACCESS_TOKEN:
        return
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "placeholder",
    }
    # Not: typing indicator için ayrı endpoint yok, read receipt kullanılır
    pass


async def _transcribe_audio(audio_bytes: bytes) -> str:
    """
    Ses bytes → OpenAI Whisper → Turkce metin (22.1l).
    OPENAI_API_KEY opsiyonel; yoksa bos donuyor.

    Destekli format: WhatsApp OGG (voice), MP3, WAV, M4A.
    Max 25MB (OpenAI limit).
    """
    if not OPENAI_KEY or not audio_bytes or len(audio_bytes) < 100:
        return ""
    if len(audio_bytes) > 25 * 1024 * 1024:
        return "[SES COK BUYUK — 25MB sinir asildi]"
    try:
        from openai import OpenAI
        import io as _io
        client = OpenAI(api_key=OPENAI_KEY)
        # WhatsApp voice genelde OGG/Opus — Whisper otomatik algilar
        fh = _io.BytesIO(audio_bytes)
        fh.name = "voice.ogg"  # filename zorunlu
        resp = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1",
            file=fh,
            language="tr",
        )
        text = (resp.text or "").strip()
        if text:
            logger.info(f"🎤 Whisper transcribed: {text[:80]}")
        return text
    except Exception as e:
        err_str = str(e).lower()
        logger.warning(f"Whisper hata: {e}")
        # 22.1m — Kullanıcı dostu mesaj (429/401/402 quota/billing hatalari icin)
        if "insufficient_quota" in err_str or "429" in err_str or "quota" in err_str:
            return "[Ses cozumu gecici kapali (bakiye yok) — yazili gonder]"
        if "401" in err_str or "invalid_api_key" in err_str:
            return "[Ses cozumu gecici kapali (api key) — yazili gonder]"
        return ""


async def _solve_photo_question(image_bytes: bytes, user_prompt: str = "", mode: str = "solve") -> str:
    """
    Fotograf uzerindeki soruyu Claude Vision ile coz.
    Kunduz benzeri: sorunun fotografini at, cozumunu al.

    mode="solve" (varsayilan): soruyu coz.
    mode="diagnose" (25.54 Hata Teshisi): fotograf OGRENCININ KENDI cozumudur —
      soruyu sifirdan cozme, NEREDE+NEDEN hata yaptigini bul + dogru yaklasim.

    22.1k guvenlik + robustluk:
    - MIME validation (magic bytes ile JPEG/PNG/WebP/GIF)
    - Size limit (5MB)
    - Graceful error handling
    """
    import base64
    if not ANTHROPIC_KEY:
        return "Foto analizi icin API anahtari gerekli."

    # Size limit — Claude Vision 20MB ama 5MB'la sinirlayalim (WP'den gelen normal foto <2MB)
    MAX_SIZE = 5 * 1024 * 1024
    if len(image_bytes) > MAX_SIZE:
        return f"⚠ Fotograf cok buyuk ({len(image_bytes)//(1024*1024)}MB). Max 5MB. Lutfen dusuk cozunurlukte tekrar gonder."

    if len(image_bytes) < 1000:
        return "⚠ Fotograf cok kucuk veya bozuk. Lutfen tekrar gonder."

    # MIME validation — magic bytes kontrolü (guvenlik: path traversal/injection onleme)
    media_type = None
    if image_bytes[:4] == b"\x89PNG":
        media_type = "image/png"
    elif image_bytes[:3] == b"\xff\xd8\xff":
        media_type = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        media_type = "image/webp"
    elif image_bytes[:3] == b"GIF":
        media_type = "image/gif"
    else:
        return "⚠ Fotograf formati tanimlanamadi (JPEG/PNG/WebP/GIF destekleniyor). Lutfen standart formatta gonder."

    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_KEY)

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    vision_prompt = (
        "Sen Fermat Egitim Kurumlari'nin uzman akademik asistanisin. "
        "Turkiye'deki YKS (TYT/AYT) ve LGS sinavlarina hazirlanan ogrencilere yardim ediyorsun.\n\n"

        "═══════════════════════════════════════════════════════════════\n"
        "🔍 ADIM 0 — FOTOGRAF SINIFLANDIRMA (ZORUNLU ILK ADIM)\n"
        "═══════════════════════════════════════════════════════════════\n"
        "25.42 (Bulgu B, 9 May Mehmet Karpuz bug): Mehmet sinav sonuc tablosu\n"
        "fotografi yolladi, bot soru zannedip 'cozulecek soru yok' dedi. KRİTİK:\n"
        "fotografi once SINIFLANDIR, sonra uygun islemi yap.\n\n"

        "ÜÇ tip:\n"
        "  TIP A — SORU (TYT/AYT/LGS test sorusu, sıklı, çözüm bekliyor)\n"
        "  TIP B — TABLO/SONUC (deneme sonuc ekrani, net listesi, puan tablosu)\n"
        "  TIP C — KONU/NOTLAR (defter sayfasi, ders notu, kavram aciklamasi)\n\n"

        "TIP TESPITI:\n"
        "  • A) sorda) cözüm) sıklar (A/B/C/D/E) varsa + soru kökü → SORU\n"
        "  • B) Sayisal değerler tabloda (net, puan, sira) + tarih/sınav adı → TABLO\n"
        "  • C) El yazısı / matbu metin / kavram açıklaması → KONU\n\n"

        "TIP B (TABLO) YANITI:\n"
        "  📊 *Sınav Sonuç Tablosu Tespit Edildi*\n"
        "  Görünen denemeler: [her sinav: ad, tarih, net, puan]\n"
        "  💡 _Bu tabloyu nasıl değerlendireyim?_\n"
        "  - 🎯 Puan tahmini istersen: \"şu an tahmini puanım\" yaz\n"
        "  - 📈 Trend analiz istersen: \"deneme analizi\" yaz\n"
        "  - 🔍 Belirli sınavın detayını istersen: o yayının adını söyle\n"
        "  → Cözmem GERIK: HİÇBİR ŞEY UYDURMA, sadece görüneni yaz.\n"
        "  → ASLA 'cozulecek soru yok' deme — kullaniciyi yonlendir.\n\n"

        "TIP C (KONU/NOTLAR) YANITI:\n"
        "  📝 *Konu Notu Tespit Edildi*\n"
        "  Konu: [tahmin et]\n"
        "  Senin notlar: [kısa ozet, 2-3 cumle]\n"
        "  💡 _Bu konuda soru cozmek ister misin? 'X konusunda quiz' yaz._\n\n"

        "TIP A (SORU) → AŞAĞIDAKI ÇÖZÜM FORMATINI KULLAN.\n"
        "═══════════════════════════════════════════════════════════════\n\n"

        "COZUM FORMATI:\n"
        "📝 *Soru Analizi*\n"
        "Ders: [ders adi]\n"
        "Konu: [konu adi]\n"
        "Zorluk: Kolay / Orta / Zor\n\n"

        "📋 *Verilenler*\n"
        "- [bilinen 1]\n"
        "- [bilinen 2]\n\n"

        "🔍 *Cozum*\n"
        "[Adim adim cozum — her adimi goster]\n\n"

        "✅ *Dogru Cevap: [X sikki]*\n\n"

        "💡 *Neden bu cevap?*\n"
        "[1-2 cumle ile aciklama]\n\n"

        "🎯 *Bu konuda dikkat*\n"
        "[Sik yapilan hatalar veya ipucu]\n\n"

        "COZUM KURALLARI:\n"
        "1. Once soruyu dikkatli oku — sekil, grafik, tablo varsa DETAYLI analiz et\n"
        "2. Verileri listele: ne biliniyorlar, ne soruluyor\n"
        "3. Hangi formul/kavram kullanilacak belirt\n"
        "4. ADIM ADIM coz — her adimi goster, birim analizini yap\n"
        "5. Sonucu KESİN ve NET belirt — dogru cevap hangisi\n"
        "6. Turkce yaz, ogrenci anlayacak dilde acikla\n"
        "7. Siklar varsa dogru sikki *bold* ile belirt (A/B/C/D/E)\n"
        "8. Yanlis siklari NEDEN yanlis oldugunu kisa acikla\n\n"

        "DERS BAZLI DIKKAT:\n"
        "- *Fizik TYT/AYT*: birimleri kontrol et (N, kg, m/s2), vektorel buyuklukler icin yon belirt, "
        "serbest cisim diyagrami ciz, enerji korunumu kontrol et\n"
        "- *Matematik TYT*: temel islemler, oran-oranti, denklem, fonksiyon, geometri temelleri. "
        "Islem adimlarini ATLAMA, her adimi goster\n"
        "- *Matematik AYT*: turev, integral, limit, diziler, kombinatorik. "
        "Formul ile birlikte GRAFIK yorumlama yapilabilir\n"
        "- *Kimya*: denklem dengelemesi kontrol et, mol hesabi birimlerini takip et, "
        "periyodik tablo bilgisi gerekebilir\n"
        "- *Biyoloji*: hucre yapisi, genetik (Mendel), ekoloji, sistem fizyolojisi. "
        "Sekil/diyagram varsa her etiketi dogru oku\n"
        "- *Turkce*: paragraf ana fikir, yardimci dusunce, sozcuk anlami, dil bilgisi. "
        "Paragrafin TAMAMINI oku, son cumleye dikkat\n\n"
        "KUNDUZ KALİTESİ — EK KURALLAR:\n"
        "- Her yanlis sikki NEDEN yanlis 1 cumle ile acikla (öğrenci tuzağı görsün)\n"
        "- Cozum sonunda: 'Bu konudan YKS'de sık çıkar — benzer soru ister misin?' sor\n"
        "- Sekil/grafik varsa: koordinat, ölçü, etiket hepsini oku ve çözümde kullan\n"
        "- Birim hatası yapma — her adımda birim takibi\n"
        "- Fotograf bulaniksa: tahmin YAPMA, fotografi daha net cek\n"
        "\n"
        "SIK UYUSMAZLIGI KURALI (KRITIK GUVENLIK KURALI):\n"
        "Hesabin hicbir sikla uyusmadiginda KESINLIKLE YASAK:\n"
        "  YASAK: En yakin sik X demek\n"
        "  YASAK: Siklarda yok ama X olabilir demek\n"
        "  YASAK: Supheyi gizleyerek yine sik gostermek\n"
        "  YASAK: Cevabi bulamayin tahmin uretip DOGRU isaretlemek\n"
        "DOGRU DAVRANIS (hesap siklara uymuyorsa):\n"
        "  1. Hesabini goster (orn: 7x7x6x5=1470 cikti)\n"
        "  2. Durustce yaz: Bu sonuc siklarda gorulmuyor, foto net olmayabilir\n"
        "  3. Fotografi daha net cek, veya siklari yazar misin?\n"
        "- *Tarih/Cografya*: donem bilgisi, harita yorumlama, neden-sonuc iliskisi\n"
        "- *Geometri*: ucgen, dortgen, daire, kati cisim. Alan/cevre/hacim formulleri. "
        "Sekildeki acilari ve kenarlari dogru oku\n"
        "- *LGS*: 8.sinif mufredat — kesirler, cebir, geometri, fen bilimleri. "
        "Soru dili daha basit ama tuzak secenekler olabilir\n\n"

        "FORMAT (WhatsApp uyumlu):\n"
        "- Basliklari *bold* yap\n"
        "- Emoji kullan (📝🔍✅💡🎯)\n"
        "- Formulleri ayri satirda yaz\n"
        "- Sonucu *bold* ile vurgula\n"
        "- Her adimi numaralandir\n"
    )
    if user_prompt:
        vision_prompt += f"\nOgrenci notu: {user_prompt}"

    # 25.54 HATA TEŞHİSİ MODU — fotograf ogrencinin KENDI cozumudur (soru degil).
    # Mevcut solve prompt'unu OVERRIDE et (dokunmadan): cozme, hatayi teshis et.
    if mode == "diagnose":
        vision_prompt = (
            "Sen Fermat Egitim Kurumlari'nin uzman akademik kocusun. Bu fotograf bir "
            "OGRENCININ KENDI COZUM DENEMESIDIR (el yazisi/cozum — sifirdan cozulecek soru DEGIL).\n\n"
            "GOREV — soruyu sifirdan cozme, OGRENCININ cozumunu TEŞHİS et:\n"
            "1. Ogrencinin cozumunu adim adim takip et\n"
            "2. NEREDE hata yapti? (hangi adim/satir — spesifik)\n"
            "3. NEDEN hata? (kavram / islem / isaret / dikkat hatasi — turunu belirt)\n"
            "4. DOGRU yaklasimi o adimdan itibaren goster\n"
            "5. Cozum DOGRUYSA: tebrik et + neyi iyi yaptigini soyle\n\n"
            "ZORUNLU: cevabin icinde 'Ders: <ders>' ve 'Konu: <konu>' satiri OLMALI "
            "(sistem konu takibi icin). 'Hata turu: <isaret/islem/kavram/dikkat/yok>' satiri ekle.\n"
            "TON: motive edici, suclamadan — 'birlikte duzeltelim'. ASLA Ingilizce. "
            "WhatsApp formati: kisa, net, *bold* vurgu, numarali adim.\n"
        )
        if user_prompt:
            vision_prompt += f"\nOgrenci notu: {user_prompt}"

    # Sync SDK — to_thread ile event loop'u bloke etmemek icin + graceful error
    try:
        response = await asyncio.to_thread(
            client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": vision_prompt},
                ],
            }],
        )
    except Exception as _vision_e:
        # Vision API hatasi (rate limit, timeout, yuksek trafik) — anlamli mesaj
        err_str = str(_vision_e).lower()
        logger.error(f"Claude Vision hata: {_vision_e}")
        if "rate" in err_str or "429" in err_str:
            return "⚠ Su anda cok yogunum, 30 saniye sonra tekrar dene 🙏"
        if "timeout" in err_str or "timed out" in err_str:
            return "⚠ Fotograf analizi uzun surdu. Daha kucuk/net bir fotograf dene."
        if "overloaded" in err_str:
            return "⚠ Vision API asiri yuklu. 1 dakika sonra tekrar dene."
        return "⚠ Fotograf analiz edilemedi. Fotografi daha net cek veya 'sorunun metnini yaz' secenegini kullan."

    if not response or not response.content:
        return "⚠ Cozum olusturulamadi, lutfen sorunun yazili halini gonder."
    answer = response.content[0].text if response.content else "Cozum olusturulamadi."

    # Token loglama
    try:
        from usage_tracker import log_event
        await log_event(
            phone="VISION", role="system", event_type="message",
            response_source="claude_vision",
            token_input=response.usage.input_tokens if response.usage else 0,
            token_output=response.usage.output_tokens if response.usage else 0,
        )
    except Exception:
        pass

    return answer


async def download_wa_media(media_id: str) -> bytes | None:
    """Meta Media API'den ses/görüntü indir."""
    if not WA_ACCESS_TOKEN:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        # Önce media URL'ini al
        r = await client.get(
            f"{GRAPH_BASE}/{media_id}",
            headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"},
        )
        if r.status_code != 200:
            logger.error(f"Media URL alınamadı: {r.status_code}")
            return None
        url = r.json().get("url", "")
        if not url:
            return None
        # İçeriği indir
        r2 = await client.get(
            url,
            headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"},
        )
        if r2.status_code == 200:
            return r2.content
        return None


# ── Webhook İmza Doğrulama ───────────────────────────────────────────────────

def verify_signature(payload: bytes, signature: str, client_ip: str = "") -> bool:
    """Meta'nın X-Hub-Signature-256 imzasını doğrula.
    WA_APP_SECRET tanımlıysa imza zorunlu, yoksa kabul et (geriye uyumlu).
    NOT (Oturum 18): Üretimde WA_APP_SECRET .env'de set edilmesi onerilir.
    """
    if not WA_APP_SECRET:
        # Secret tanımsız — geriye uyumlu mod (Meta webhook'larini engellemez)
        return True
    expected = "sha256=" + hmac.new(
        WA_APP_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Agent Session Yönetimi ───────────────────────────────────────────────────

# Oturum 25.29 — Kapı 6 / Brief #4: paralel v2 agent (LiveSignalBus)
# Strateji B: production'a dokunma, sadece Neo'nun hattında v2 aktif.
# Rollback: AGENT_V2_PHONES = set() — tek satır, anında tüm kullanıcılar v1'e döner.
AGENT_V2_PHONES: set[str] = {"905051256802"}  # Neo (Zeki Goksal — admin)


def _select_agent_class(phone: str):
    """Telefon → uygun agent class. v2 listedeyse FermatCoreAgentV2, değilse v1."""
    if phone in AGENT_V2_PHONES:
        try:
            from fermat_core_agent_v2 import FermatCoreAgentV2
            return FermatCoreAgentV2, "v2"
        except Exception as e:
            # v2 import hatası → v1'e graceful fallback (production etki yok)
            logger.warning(f"[BRIDGE] v2 import fail, v1 fallback: {e}")
    from fermat_core_agent import FermatCoreAgent
    return FermatCoreAgent, "v1"


def get_agent(phone: str):
    """Telefon başına tek agent instance — konuşma geçmişi korunur + DB'den yüklenir.

    25.29: Kapı 6 — AGENT_V2_PHONES'da olan telefonlar V2 alır (LiveSignalBus aktif),
           diğerleri V1'de kalır (production etki YOK).

    25.43-ITER5 FIX (Neo halüsinasyon root cause): test_mode'da agent history
    HER ÇAĞRIDA TEMİZ olmalı — sıralı testlerde önceki konunun (birim çember)
    bağlamı sonraki teste (türev) sızıyor, Cerebras yanlış konuyu cevaplıyordu.
    """
    # Test mode: her cagrı icin temiz agent (kontamine bağlam yok)
    try:
        from test_mode import is_test_context
        if is_test_context():
            # Test phone icin fresh agent — eski history at
            if phone in _AGENT_SESSIONS:
                del _AGENT_SESSIONS[phone]
    except Exception:
        pass

    if phone not in _AGENT_SESSIONS:
        try:
            AgentClass, ver = _select_agent_class(phone)
            agent = AgentClass()
            _AGENT_SESSIONS[phone] = agent
            logger.info(f"Yeni agent session ({ver}): {phone}")

            # 25.41 (Neo bug 7 May, Brief #18): ThreadPoolExecutor + asyncio.run() ANTI-PATTERN kaldırıldı.
            # ESKI: yeni event loop açıyordu → mevcut asyncpg pool'la çakışıyordu →
            # "cannot perform operation: another operation is in progress" + ConnectionDoesNotExistError.
            # YENI: history yüklemesini process_message tarafına ertele (async context'te).
            # Agent burada history=[] ile başlatılır; ilk mesaj geldiğinde process_message
            # async olarak yükler. Bu sayede pool mevcut event loop'ta düzgün çalışır.
            # 25.43-ITER5: test mode'da history yukleme SKIP (her test temiz)
            try:
                from test_mode import is_test_context
                if is_test_context():
                    agent._needs_history_load = False
                else:
                    agent._needs_history_load = True
            except Exception:
                agent._needs_history_load = True  # Lazy flag — process_message async yükler

        except Exception as e:
            logger.error(f"Agent oluşturulamadı: {e}")
            return None
    return _AGENT_SESSIONS[phone]


# Ogrenci etkilesim istatistikleri {phone: {konu: sayi}}
_STUDENT_INTERACTION_STATS: dict[str, dict[str, int]] = {}


# ── Mesaj İşleyici ────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Telefon numarasini normalize et: +905xx → 905xx, 05xx → 905xx
    OTURUM 22.7 (21 Nisan) — phone_utils.normalize_phone delegasyonu (tek kaynak)."""
    from phone_utils import normalize_phone
    return normalize_phone(phone) or ""


async def process_message(phone: str, text: str, audio_bytes: bytes | None = None, channel: str = "whatsapp",
                          _stream_queue=None) -> str:
    """
    Gelen mesajı işle → agent yanıtı döndür.
    audio_bytes verilirse önce transkripsiyon yapılır.

    Args:
        phone: Telefon (normalize edilecek)
        text: Mesaj metni
        audio_bytes: Ses (WhatsApp voice)
        channel: "whatsapp" | "web" — web ise WA'ya filler/followup GÖNDERİLMEZ
        _stream_queue: asyncio.Queue — Faz 4 native streaming (web chat).
                       Claude tokens delta'ları ('chunk', text) olarak yazılır.

    Akış:
      0. Numara normalizasyonu + blok/kayit kontrolu
      1. Ses → Whisper transkripsiyon
      2. Özel komutlar (sıfırla, yardım)
      3. IntentParser → followup soru varsa kullanıcıya sor
      4. FermatCoreAgent.run() → tam yanıt
    """
    # ── 0. Numara normalizasyonu + guvenlik kontrolleri ───────────────────────
    phone = _normalize_phone(phone)

    # ── TEST MODE detection (10 May Neo direktif) ──────────────────────────────
    # is_test=True ise: side-effect'ler (insights/memory/alert/sentiment) skip,
    # rate-limit gevsek, usage_log'a is_test=true yazilir. Asil cevap normal uretilir.
    try:
        from test_mode import detect_test_context, set_test_mode, strip_test_marker
        _is_test, _test_id = detect_test_context(phone, text)
        if _is_test:
            set_test_mode(True, _test_id)
            # [TEST:id] prefix'i temizle — agent gercek soruyu gorsun
            text = strip_test_marker(text)
            logger.info(f"[TEST_MODE] active phone={phone[-4:]} test_id={_test_id} text={text[:60]!r}")
    except Exception as _te:
        logger.debug(f"[TEST_MODE] init fail: {_te}")

    # ── Split continuation leak guard (13:58 bug defansi) ──
    # Eğer text bir dict str repr'i gibi gözüküyorsa (örn "{'type': 'split_continuation'...")
    # → bu user mesajı değil, payload sızıntısı. Reddet.
    if text and text.lstrip().startswith("{'type':") and "split_continuation" in text:
        logger.error(f"[LEAK GUARD] Split payload text olarak geldi (phone={phone[-4:]}), reddedildi")
        # Split varsa, "devam" gibi davran → 2. parçayı tekrar gonder
        split_info = _PENDING_SPLIT.pop(phone, None)
        if split_info and split_info.get("full_response"):
            return f"_Özür, mesaj parçalanması sırasında bir şey kayboldu — tekrar gönderiyorum:_\n\n{split_info['full_response']}"
        return "Mesajını anlayamadım, tekrar yazar mısın?"

    # Bloklu mu?
    if await _is_phone_blocked(phone):
        logger.warning(f"BLOKLU numara mesaj gonderdi: {phone}")
        try:
            from usage_tracker import log_event
            await log_event(phone=phone, event_type="blocked")
        except Exception:
            pass
        return ""  # Sessizce reddet, yanit verme

    # Kayitli mi?
    profile = await _is_phone_registered(phone)
    is_registered = profile is not None

    # ── ONBOARDING (Talimat #77, Neo 22:17) ──────────────────────
    # Kayıtlı kullanıcı İLK KEZ mesaj atıyorsa → hoşgeldin + WP+Web tanıtım
    # welcomed_at = NULL ise henüz onboard değil.
    #
    # Bug fix 23 Nisan — RACE CONDITION:
    # SELECT + UPDATE atomik değildi. Enes 22 Nisan 12:13:28 (ilk mesaj) ve 12:13:41
    # (2. mesaj) arasında 13 saniye geçti ama ikinci mesajda da onboarding menüsü
    # geldi (backfill kayıt araya girmemişti). Artık:
    # UPDATE ... WHERE welcomed_at IS NULL RETURNING — CLAIM mekanizması.
    # Sadece BIR işlem gerçekten update eder, diğerleri 0 satır alır → onboarding atlar.
    if is_registered and profile:
        try:
            from db_pool import db_fetchval, db_execute, db_fetchrow
            # Oturum 25.6 D6: datetime scope bug fix — fonksiyon icinde local rebind
            # oluyordu, 'datetime' unbound hatasi veriyordu. Local import cozer.
            from datetime import datetime as _dt_onb
            # ATOMIK CLAIM: welcomed_at NULL ise NOW() set et ve satırı dön
            claim_row = await db_fetchrow(
                """
                UPDATE acl_users
                SET welcomed_at = NOW()
                WHERE REPLACE(phone,'+','') = $1 AND welcomed_at IS NULL
                RETURNING id
                """,
                phone,
            )
            welcomed = None if claim_row else _dt_onb.now()  # claim başarılı = NULL'du = onboard et
            if welcomed is None:
                # İlk mesaj — NULL. Onboarding mesajı hazırla (ama gönderme, işle-önce)
                role = (profile.get("role") or "ogrenci").lower()
                name = (profile.get("full_name") or profile.get("first_name") or "").split()[0]
                _name_part = f"*{name}* " if name else ""

                if role == "ogretmen":
                    onboard_msg = (
                        f"🎉 Merhaba {_name_part}Hocam! Fermat AI'a hoş geldiniz.\n\n"
                        f"Ben FermatAI — öğrencilerinizin sınav analizi, zayıf konu tespiti, "
                        f"etüt önerileri ve pedagojik veri sağlayan asistanınızım.\n\n"
                        f"📱 *WhatsApp'tan* hızlı sorular sorabilirsiniz:\n"
                        f"• \"Sınıfımın son deneme özeti\"\n"
                        f"• \"Zayıf konu haritası\"\n"
                        f"• \"Bu hafta ders programım\"\n\n"
                        f"💻 *Daha detaylı analizler* için web arayüzümüz:\n"
                        f"🌐 https://www.fermategitimkurumlari.com/fermatai\n"
                        f"_WP'den \"web kodu\" yazın, 6 haneli kod gelir — web'e de girebilirsiniz. "
                        f"Grafikler, tablolar ve uzun raporlar orada çok daha güzel görünür._\n\n"
                        f"Herhangi bir sorunuz için yazın, birlikte keşfedelim. 🎯"
                    )
                elif role in ("mudur", "yonetim"):
                    onboard_msg = (
                        f"🎉 Hoş geldiniz {_name_part}— FermatAI kurum yönetim asistanınız.\n\n"
                        f"📊 Kurum geneli raporlar, öğretmen performansı, risk tespitleri — WhatsApp'tan sorabilirsiniz.\n\n"
                        f"💻 Kapsamlı analiz ve grafikler için web:\n"
                        f"🌐 https://www.fermategitimkurumlari.com/fermatai\n"
                        f"_\"web kodu\" yazın, giriş kodu gelir._\n\n"
                        f"Hazır komutlar için web'de ☰ menü var — tek tıkla rapor çekebilirsiniz."
                    )
                elif role == "rehber":
                    onboard_msg = (
                        f"🎉 Merhaba {_name_part}Hocam! FermatAI'a hoş geldiniz.\n\n"
                        f"💙 Öğrencilerin duygusal sinyalleri, rehberlik notları, risk analizi — hepsi elinizin altında.\n\n"
                        f"💻 Web arayüzü daha detaylı:\n"
                        f"🌐 https://www.fermategitimkurumlari.com/fermatai\n"
                        f"_\"web kodu\" yazın, giriş yapabilirsiniz._"
                    )
                else:  # ogrenci
                    onboard_msg = (
                        f"🎉 Merhaba {_name_part}— FermatAI'a hoş geldin!\n\n"
                        f"Ben senin kişisel akademik koçunum. Her soruna cevap veririm:\n"
                        f"• 📊 Deneme analizin\n"
                        f"• 📉 Zayıf konuların\n"
                        f"• 📅 Çalışma planı\n"
                        f"• 📸 Foto ile soru çözüm\n\n"
                        f"💻 *Daha geniş ekran ve grafikler için* web arayüzüm:\n"
                        f"🌐 https://www.fermategitimkurumlari.com/fermatai\n"
                        f"_\"web kodu\" yaz, sana 6 haneli kod geleceğim — web'de konuşmak istersen kullan._\n\n"
                        f"Başlayalım mı? Ne sormak istersin? 🎯"
                    )

                # welcomed_at zaten atomik CLAIM ile set edildi (yukarıda).
                # Onboarding gönder (sadece WP, web kanalı zaten UI gösteriyor)
                if channel == "whatsapp":
                    try:
                        await send_wa_message(phone, onboard_msg)
                        logger.info(f"🎉 Onboarding gönderildi: {phone[-4:]} ({name}, {role})")
                    except Exception as _oe:
                        logger.warning(f"Onboarding gönderme hatası: {_oe}")
                    # İlk mesajı normal pipeline'a al — onboarding'e devamla cevap dönmeli
                    # (Kullanıcı bir soru sorduysa o sorunun cevabı da gelsin)
                    # Özel durum: mesaj sadece "merhaba"/"selam" ise onboard'la yetinebiliriz
                    first_msg = (text or "").lower().strip()
                    if first_msg in ("merhaba", "selam", "selamun aleykum", "sa", "hey", "hi", "iyi günler"):
                        return ""  # Onboard zaten ınterim, return
        except Exception as _onboard_err:
            logger.debug(f"Onboarding akışı hatası: {_onboard_err}")

    # Kayitli degilse → FERMATAI kurumsal pazarlama modu
    if not is_registered:
        # Oturum 18: PII masking — kayitsiz numara + mesaj icerigi birlikte LOG'da OLMAZ
        logger.info(f"KAYITSIZ numara: ***{phone[-4:]} — mesaj uzunluk: {len(text or '')} char")
        try:
            from usage_tracker import log_event
            await log_event(phone=phone, event_type="unknown")
        except Exception:
            pass
        if not _check_rate_limit(phone, is_registered=False, msg_len=len(text or "")):
            return ""

        # Önce hızlı yanıt dene — token harcamadan
        try:
            from guest_responses import try_guest_response
            guest_fast = await try_guest_response(text)
            if guest_fast:
                logger.info(f"  [GUEST-FAST] Kayitsiz numara hizli yanit")
                # Lead log
                try:
                    await db_execute("""
                        CREATE TABLE IF NOT EXISTS lead_contacts (
                            id SERIAL PRIMARY KEY, phone TEXT, message TEXT,
                            response TEXT, created_at TIMESTAMP DEFAULT NOW())""")
                    await db_execute(
                        "INSERT INTO lead_contacts (phone, message, response) VALUES ($1, $2, $3)",
                        phone, text[:500], guest_fast[:500])
                except Exception:
                    pass
                return guest_fast
        except Exception:
            pass

        # Hızlı yanıt bulunamadı — Claude ile diyalog (ama kısıtlı yetki)
        try:
            agent = get_agent(phone)
            if not agent:
                # Oturum 25.29: v2-aware fallback (Neo hattıysa v2)
                AgentClass, ver = _select_agent_class(phone)
                _AGENTS[phone] = AgentClass()
                agent = _AGENTS[phone]
                logger.info(f"Inline fallback agent ({ver}): {phone}")
            response = await agent.run(user_input=text, caller_phone=phone)

            # Yabancı numara logla — iletişim bilgisi çıkar
            try:
                await db_execute("""
                    CREATE TABLE IF NOT EXISTS lead_contacts (
                        id SERIAL PRIMARY KEY,
                        phone TEXT,
                        message TEXT,
                        response TEXT,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                await db_execute(
                    "INSERT INTO lead_contacts (phone, message, response) VALUES ($1, $2, $3)",
                    phone, text[:500], (response or "")[:500])
            except Exception:
                pass

            return response
        except Exception as e:
            logger.error(f"Kayitsiz numara agent hatasi: {e}")
            return (
                "Merhabalar! *Fermat Egitim Kurumlari* dijital asistaniyim.\n\n"
                "Size nasil yardimci olabilirim? Programlarimiz, egitim modelimiz "
                "veya randevu hakkinda bilgi almak ister misiniz?\n\n"
                "Tel: +90 546 260 54 46\n"
                "Web: fermategitimkurumlari.com/randevu"
            )

    # ── NEO KOMUTLARI (Mimar/Admin ozel) ─────────────────────────────────────
    if phone == NEO_PHONE and text:
        neo_lower = text.strip().lower()

        # ── EYOTEK KOMUTLARI (admin/mudur) ──────────────────────────────
        import re as _re_eyo
        if _re_eyo.search(r'eyotek|et[uü]t\s*(yoklama|durum|bug[uü]n|bak)', neo_lower):
            try:
                from eyotek_knowledge.eyotek_commands import handle_eyotek_command
                eyo_resp = await handle_eyotek_command(text, phone, profile.get("role", "admin"))
                if eyo_resp:
                    return eyo_resp
            except Exception as _eyo_err:
                logger.warning(f"Eyotek komut hatasi: {_eyo_err}")

        # Kullanici bloklama: "blokla 905xxxxxxxxx" veya "blokla Ali"
        if neo_lower.startswith("blokla "):
            target = text[7:].strip()
            target_phone = _normalize_phone(target) if target.replace("+","").isdigit() else None
            if target_phone:
                try:
                    await db_execute(
                        "INSERT INTO blocked_numbers (phone, reason, blocked_by) VALUES ($1, 'Neo komutu', $2) ON CONFLICT DO NOTHING",
                        target_phone, phone)
                    return f"Numara bloklandi: {target_phone}"
                except Exception as e:
                    return f"Bloklama hatasi: {e}"
            return "Kullanim: blokla 905xxxxxxxxx"

        # Blok kaldirma: "blok kaldir 905xxxxxxxxx"
        if neo_lower.startswith("blok kaldir "):
            target_phone = _normalize_phone(text[12:].strip())
            try:
                await db_execute("DELETE FROM blocked_numbers WHERE phone=$1", target_phone)
                return f"Blok kaldirildi: {target_phone}"
            except Exception as e:
                return f"Hata: {e}"

        # Yetki degistirme: "yetki 905xx ogretmen"
        if neo_lower.startswith("yetki "):
            parts = text[6:].strip().split()
            if len(parts) >= 2:
                target_phone = _normalize_phone(parts[0])
                new_role = parts[1].lower()
                # Admin yetkisi ASLA başkasına verilemez — NEO tek ve değişmez
                if new_role == "admin":
                    return "Admin yetkisi baska birine atanamaz. NEO tek ve degisemezdir."
                if new_role in ("mudur", "ogretmen", "rehber", "ogrenci", "veli"):
                    try:
                        await db_execute(
                            "UPDATE acl_users SET role=$1 WHERE phone=$2", new_role, target_phone)
                        return f"Yetki guncellendi: {target_phone} → {new_role}"
                    except Exception as e:
                        return f"Hata: {e}"
            return "Kullanim: yetki 905xxxxxxxxx ogretmen"

        # Kullanici ekle: "ekle ogretmen Vedat Oztekin 905xxxxxxxxx"
        if neo_lower.startswith("ekle "):
            parts = text[5:].strip().split()
            if len(parts) >= 3:
                new_role = parts[0].lower()
                new_phone = _normalize_phone(parts[-1])
                new_name = " ".join(parts[1:-1])
                if new_role == "admin":
                    return "Admin yetkisi baska birine atanamaz. NEO tek ve degisemezdir."
                if new_role in ("mudur", "ogretmen", "rehber", "ogrenci", "veli"):
                    try:
                        await db_execute("""
                            INSERT INTO acl_users (phone, full_name, role, is_active, notes)
                            VALUES ($1, $2, $3, TRUE, 'Neo WP komutu')
                            ON CONFLICT (phone) DO UPDATE SET role=$3, full_name=$2, is_active=TRUE
                        """, new_phone, new_name, new_role)
                        return f"*Kullanici eklendi:*\nAd: {new_name}\nTel: {new_phone}\nRol: {new_role}"
                    except Exception as e:
                        return f"Ekleme hatasi: {e}"
            return "Kullanim: ekle ogretmen Ad Soyad 905xxxxxxxxx"

        # Kullanici sil/deaktif: "sil 905xxxxxxxxx"
        if neo_lower.startswith("sil "):
            target_phone = _normalize_phone(text[4:].strip())
            try:
                row = await db_fetchrow("SELECT full_name, role FROM acl_users WHERE phone=$1", target_phone)
                if row:
                    await db_execute("UPDATE acl_users SET is_active=FALSE WHERE phone=$1", target_phone)
                    return f"*Kullanici deaktif edildi:*\n{row['full_name']} ({row['role']})\nTel: {target_phone}"
                else:
                    return f"Bu numara sistemde kayitli degil: {target_phone}"
            except Exception as e:
                return f"Silme hatasi: {e}"

        # Bekleyen onaylar: "onaylar"
        if neo_lower in ("onaylar", "bekleyen", "pending"):
            try:
                # Talimatlar
                talimatlar = await db_fetch(
                    "SELECT id, talimat, to_char(created_at, 'DD.MM HH24:MI') as ts FROM admin_talimat WHERE durum='bekliyor' ORDER BY created_at")
                # Ogrenme raporlari
                reports = await db_fetch(
                    "SELECT id, errors_count, improvements, to_char(created_at, 'DD.MM HH24:MI') as ts FROM auto_learning_log ORDER BY created_at DESC LIMIT 3")

                lines = ["*Neo Kontrol Paneli*\n"]
                if talimatlar:
                    lines.append(f"\n*Bekleyen Talimatlar ({len(talimatlar)}):*")
                    for t in talimatlar:
                        lines.append(f"  #{t['id']} [{t['ts']}] {t['talimat'][:60]}")
                else:
                    lines.append("\nBekleyen talimat yok.")

                if reports:
                    lines.append(f"\n*Son Ogrenme Raporlari:*")
                    for r in reports:
                        imp = r['improvements'] or 'Yok'
                        lines.append(f"  [{r['ts']}] {r['errors_count']} hata | {imp[:50]}")

                return "\n".join(lines)
            except Exception as e:
                return f"Onay sorgu hatasi: {e}"

        # Talimat onayla: "onayla 5" veya "onayla hepsi"
        if neo_lower.startswith("onayla "):
            target = text[7:].strip()
            try:
                if target.lower() == "hepsi":
                    count = await db_fetchval("SELECT COUNT(*) FROM admin_talimat WHERE durum='bekliyor'")
                    await db_execute("UPDATE admin_talimat SET durum='onaylandi' WHERE durum='bekliyor'")
                    return f"✅ *{count or 0} talimat onaylandi.*"
                elif target.isdigit():
                    await db_execute("UPDATE admin_talimat SET durum='onaylandi' WHERE id=$1", int(target))
                    return f"Talimat #{target} onaylandi."
            except Exception as e:
                return f"Onay hatasi: {e}"
            return "Kullanim: onayla 5 veya onayla hepsi"

        # Kullanıcı notları: "notlar" — Neo emirleri vs diğer tavsiyeler ayrı
        if neo_lower in ("notlar", "feedbackler", "geri bildirimler", "bildirimler"):
            try:
                # Neo emirleri (son 20)
                neo_notes = await db_fetch("""
                    SELECT id, LEFT(feedback,80) as not_text, status, to_char(created_at, 'DD.MM HH24:MI') as ts
                    FROM user_feedback WHERE phone='905051256802'
                    ORDER BY created_at DESC LIMIT 10
                """)
                # Diğer kullanıcı tavsiyeleri (onay bekleyen)
                user_notes = await db_fetch("""
                    SELECT id, full_name, role, LEFT(feedback,80) as not_text,
                           to_char(created_at, 'DD.MM HH24:MI') as ts
                    FROM user_feedback WHERE phone != '905051256802' AND status='yeni'
                    ORDER BY created_at DESC LIMIT 10
                """)

                lines = []
                if neo_notes:
                    lines.append(f"👑 *Neo Talimatlari ({len(neo_notes)}):*\n")
                    for n in neo_notes:
                        st = "✅" if n['status'] == 'islendi' else "⏳"
                        lines.append(f"  {st} #{n['id']} [{n['ts']}] {n['not_text']}")
                    lines.append("")

                if user_notes:
                    lines.append(f"📋 *Kullanici Tavsiyeleri — Onay Bekliyor ({len(user_notes)}):*\n")
                    for n in user_notes:
                        lines.append(f"  📝 #{n['id']} [{n['ts']}] *{n['full_name']}* ({n['role']})")
                        lines.append(f"     {n['not_text']}")
                    lines.append(f"\n_Onaylamak icin: onayla #{{}}_")
                else:
                    lines.append("📋 Onay bekleyen tavsiye yok.")

                return "\n".join(lines) if lines else "Henuz not yok."
            except Exception as e:
                return f"Not sorgu hatasi: {e}"

        # Lead raporu: "leadler" veya "potansiyel"
        if neo_lower in ("leadler", "potansiyel", "leads", "yabanci"):
            try:
                leads = await db_fetch("""
                    SELECT phone, COUNT(*) as mesaj, MIN(created_at) as ilk, MAX(created_at) as son
                    FROM lead_contacts GROUP BY phone ORDER BY son DESC LIMIT 10
                """)
                if not leads:
                    return "Henuz lead kaydı yok."
                lines = [f"*Potansiyel Musteriler ({len(leads)}):*\n"]
                for l in leads:
                    lines.append(f"  {l['phone']} — {l['mesaj']} mesaj ({l['ilk'].strftime('%d.%m')})")
                return "\n".join(lines)
            except Exception as e:
                return f"Lead hatasi: {e}"

        # Ogrenme raporu: "ogrenme"
        if neo_lower in ("ogrenme", "ogrenme raporu", "learning"):
            try:
                from auto_learner import run_auto_learning
                report = await run_auto_learning()
                if report:
                    lines = ["*Ogrenme Raporu*\n"]
                    lines.append(f"Analiz: {report.get('analyzed_messages',0)} mesaj")
                    lines.append(f"Hata: {report.get('errors_found',0)}")
                    imps = report.get('improvements_applied', [])
                    if imps:
                        lines.append(f"\n*Iyilestirmeler:*")
                        for i in imps:
                            lines.append(f"  - {i}")
                    topics = report.get('frequent_topics', {})
                    if topics:
                        lines.append(f"\n*Sik Konular:*")
                        for k, v in list(topics.items())[:5]:
                            lines.append(f"  - {k}: {v}x")
                    return "\n".join(lines)
                return "Yeterli veri yok."
            except Exception as e:
                return f"Ogrenme hatasi: {e}"

        # Neo mesaj gönderme: "mesaj 905xx: merhaba" veya "mesaj Ali: merhaba"
        if neo_lower.startswith("mesaj ") or neo_lower.startswith("yaz ") or neo_lower.startswith("gonder "):
            prefix_len = 6 if neo_lower.startswith("mesaj ") else 4 if neo_lower.startswith("yaz ") else 7
            rest = text[prefix_len:].strip()
            if ":" not in rest:
                return "Kullanim: mesaj Ad Soyad: mesaj metni\nVeya: mesaj 905xxxxxxxxx: mesaj metni"

            target_part, msg_text = rest.split(":", 1)
            target_part = target_part.strip()
            msg_text = msg_text.strip()
            if not msg_text:
                return "Mesaj metni bos olamaz."

            target_phone = None

            # Numara mı isim mi? (Oturum Mentenans: phone_utils delegasyon)
            from phone_utils import normalize_phone as _norm_tp
            clean_target = _norm_tp(target_part) or target_part
            if clean_target.isdigit() and len(clean_target) >= 10:
                target_phone = _normalize_phone(target_part)
            else:
                # İsimle ara — önce acl_users, sonra students
                try:
                    # Türkçe karakter dönüşümü
                    search = target_part
                    _tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
                    search_ascii = search.translate(_tr_map)
                    # Önce acl_users'dan ara
                    row = await db_fetchrow(
                        "SELECT phone, full_name FROM acl_users WHERE "
                        "(LOWER(full_name) LIKE LOWER($1) OR TRANSLATE(LOWER(full_name),'çğıöşü','cgiosu') LIKE LOWER($2)) "
                        "AND is_active=TRUE LIMIT 1",
                        f"%{search}%", f"%{search_ascii}%")
                    if not row:
                        row = await db_fetchrow(
                            "SELECT phone, full_name FROM students WHERE "
                            "(LOWER(full_name) LIKE LOWER($1) OR TRANSLATE(LOWER(full_name),'çğıöşü','cgiosu') LIKE LOWER($2)) "
                            "AND phone IS NOT NULL LIMIT 1",
                            f"%{search}%", f"%{search_ascii}%")
                    if row and row['phone']:
                        target_phone = _normalize_phone(row['phone'])
                        found_name = row['full_name']
                        logger.info(f"  [NEO-MESAJ] {target_part} → {found_name} ({target_phone})")
                except Exception as e:
                    logger.error(f"  [NEO-MESAJ] Isim arama hatasi: {e}")

            if not target_phone:
                return f"'{target_part}' icin telefon numarasi bulunamadi."

            success = await send_wa_message(target_phone, msg_text)
            if success:
                return f"✅ Mesaj gonderildi."
            else:
                return f"Mesaj gonderilemedi — numara WP'de aktif olmayabilir."

        # Neo yardim menusu
        if neo_lower in ("neo", "komutlar", "neo yardim", "neo help"):
            return (
                "👑 *NEO KONTROL PANELİ*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📨 *Mesaj*\n"
                "  mesaj Ad Soyad: metin\n"
                "  mesaj 905xx: metin\n\n"
                "👥 *Kullanici*\n"
                "  ekle ogretmen Ad 905xx\n"
                "  sil 905xx\n"
                "  yetki 905xx mudur\n"
                "  blokla / blok kaldir\n\n"
                "📋 *Notlar & Talimat*\n"
                "  notlar\n"
                "  talimatlar\n"
                "  onaylar\n"
                "  onayla 5 / onayla hepsi\n\n"
                "📊 *Raporlar*\n"
                "  rapor — gunluk ozet\n"
                "  leadler — potansiyel musteriler\n"
                "  ogrenme — AI analiz raporu\n"
                "  trend — haftalik\n"
                "  sistem — servis durumu\n\n"
                "🔧 *Sistem*\n"
                "  token — WA token kontrol\n\n"
                "_Detay icin komutu yazin._"
            )

        # Gunluk kullanim raporu
        if neo_lower in ("rapor", "gunluk", "günlük", "log", "kullanim"):
            try:
                from usage_tracker import get_today_summary, update_daily_stats
                await update_daily_stats()
                return await get_today_summary()
            except Exception as e:
                return f"Rapor hatasi: {e}"

        # Self-Observation: kalite raporu
        if neo_lower in ("kalite", "kalite raporu", "kalite rapor", "quality"):
            try:
                from self_observer import get_quality_summary
                summary = await get_quality_summary(24)
                lines = ["📊 *KALİTE RAPORU — Son 24 Saat*\n"]
                lines.append(f"Toplam değerlendirme: *{summary['toplam']}* cevap\n")
                if summary['grade_dagilim']:
                    lines.append("*Grade Dağılımı:*")
                    for r in summary['grade_dagilim']:
                        emoji = {'A':'🟢','B':'🟢','C':'🟡','D':'🔴','F':'🔴'}.get(r['grade'], '⚪')
                        lines.append(f"  {emoji} *{r['grade']}*: {r['cnt']} cevap | halu={r['avg_halu']:.2f}")
                if summary['top_sorunlar']:
                    lines.append("\n*En Yaygın Sorunlar:*")
                    for r in summary['top_sorunlar'][:7]:
                        lines.append(f"  • {r['cnt']:3d}x — _{r['sorun']}_")
                lines.append("\n_'son hatalar' yazarak kötü cevapları görebilirsin_")
                return "\n".join(lines)
            except Exception as e:
                return f"Kalite raporu hatasi: {e}"

        # Son hatalar — düşük grade'li cevaplar
        if neo_lower in ("son hatalar", "son hata", "kotu cevaplar", "kötü cevaplar", "halusinasyonlar"):
            try:
                rows = await db_fetch("""
                    SELECT phone, role, user_message, bot_response, sorunlar, grade,
                           to_char(created_at, 'DD.MM HH24:MI') as ts
                    FROM quality_log
                    WHERE grade IN ('D','F') AND created_at >= NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC LIMIT 10
                """)
                if not rows:
                    return "Son 24 saatte düşük kalite (D/F grade) cevap yok ✅"
                lines = [f"⚠️ *Son 24 Saat — Düşük Kalite Cevaplar* ({len(rows)})\n"]
                for r in rows:
                    ph = r['phone'][-4:] if r['phone'] else '?'
                    sorunlar = ', '.join(r['sorunlar'] or [])[:80]
                    lines.append(f"\n*[{r['grade']}] {r['ts']} ...{ph} ({r['role']})*")
                    lines.append(f"  USER: _{(r['user_message'] or '')[:60]}_")
                    lines.append(f"  BOT: {(r['bot_response'] or '')[:80]}...")
                    lines.append(f"  ⚡ Sorun: {sorunlar}")
                return "\n".join(lines)
            except Exception as e:
                return f"Son hatalar hatasi: {e}"

        # Manuel yoklama sync (admin tetikleyebilir)
        if neo_lower in ("yoklama sync", "sync yoklama", "sync attendance", "şimdi sync et"):
            try:
                from sync_attendance import run_attendance_sync, ensure_data_freshness_table
                await ensure_data_freshness_table()
                result = await run_attendance_sync(days=1)
                if result['success']:
                    return f"✅ Yoklama sync başarılı: *{result['count']}* yeni/güncel kayıt"
                else:
                    return f"❌ Yoklama sync başarısız: {result.get('reason', 'bilinmeyen')}"
            except Exception as e:
                return f"Sync hatasi: {e}"

        # Self-Diagnosis: tani raporu
        if neo_lower in ("tani", "tanı", "diagnose", "diagnosis", "tani raporu", "kok neden"):
            try:
                from self_diagnosis import format_diagnosis_report
                return await format_diagnosis_report(24)
            except Exception as e:
                return f"Diagnosis hatasi: {e}"

        # Konuşmaları incele — hata pattern + cozum (en kapsamli)
        if neo_lower in ("konuşmalara bak", "konusmalara bak", "konuşmaları incele",
                         "konusmalari incele", "incele konuşmaları", "hata bul"):
            try:
                from self_diagnosis import format_diagnosis_report
                return await format_diagnosis_report(24)
            except Exception as e:
                return f"Inceleme hatasi: {e}"

        # Konu zorluk haritasi (kurum geneli)
        if neo_lower in ("zorluk", "zorluk haritasi", "zayif konular kurum", "kurum zayif"):
            try:
                from topic_difficulty_map import format_kurum_raporu
                return await format_kurum_raporu(top=10)
            except Exception as e:
                return f"Zorluk haritasi hatasi: {e}"
        if neo_lower.startswith(("zorluk ", "zayif ")):
            try:
                from topic_difficulty_map import format_kurum_raporu
                ders = text.split(" ", 1)[1].strip()
                return await format_kurum_raporu(ders_filtre=ders, top=10)
            except Exception as e:
                return f"Zorluk haritasi hatasi: {e}"

        # Suggestion Engine (Faz 3 — iyilestirme onerileri)
        if neo_lower in ("oneri listesi", "öneri listesi", "oneriler", "öneriler",
                         "iyilestirme onerileri", "iyileştirme önerileri"):
            try:
                from suggestion_engine import list_pending_suggestions
                return await list_pending_suggestions(20)
            except Exception as e:
                logger.error(f"Oneri listesi hatasi: {e}")
                return f"Oneri listesi hatasi: {e}"

        if neo_lower in ("oneri uret", "öneri üret", "oneri tara", "öneri tara"):
            try:
                from suggestion_engine import generate_suggestions_from_diagnosis, save_suggestions
                suggestions = await generate_suggestions_from_diagnosis(48)
                result = await save_suggestions(suggestions)
                return (f"✅ {result['eklenen']} yeni oneri uretildi (toplam {result['toplam']}).\n"
                        f"_'oneri listesi' yaz, hepsini gor_")
            except Exception as e:
                logger.error(f"Oneri uretim hatasi: {e}")
                return f"Oneri uretim hatasi: {e}"

        if neo_lower.startswith(("oneri detay ", "öneri detay ")):
            try:
                from suggestion_engine import get_suggestion_detail
                sid = int(text.split()[-1])
                return await get_suggestion_detail(sid)
            except Exception as e:
                return f"Oneri detay hatasi: {e}"

        if neo_lower.startswith(("oneri onayla ", "öneri onayla ")):
            try:
                from suggestion_engine import review_suggestion
                sid = int(text.split()[-1])
                return await review_suggestion(sid, 'onayla', reviewer=phone)
            except Exception as e:
                return f"Oneri onay hatasi: {e}"

        if neo_lower.startswith(("oneri reddet ", "öneri reddet ")):
            try:
                from suggestion_engine import review_suggestion
                sid = int(text.split()[-1])
                return await review_suggestion(sid, 'reddet', reviewer=phone)
            except Exception as e:
                return f"Oneri red hatasi: {e}"

        # Filler/UX test: "filler dene [intent]"
        if neo_lower.startswith(("filler dene", "filler test", "ux test")):
            try:
                from conversation_flow import _PRE_FILLERS, pick_filler
                parts = text.split()
                if len(parts) >= 3:
                    intent = parts[2]
                    if intent not in _PRE_FILLERS:
                        return f"Bilinmeyen intent. Mevcutlar: {', '.join(_PRE_FILLERS.keys())}"
                    msg = pick_filler(intent, phone)
                    return f"📨 *Filler ornegi ({intent}):*\n\n{msg}"
                else:
                    # Tum kategorileri listele
                    lines = ["📨 *FILLER KATEGORILERI:*\n"]
                    for k, vals in _PRE_FILLERS.items():
                        lines.append(f"  • *{k}* ({len(vals)} varyasyon)")
                    lines.append("\n_Kullanim: filler dene puan_tahmin_")
                    return "\n".join(lines)
            except Exception as e:
                return f"Filler test hatasi: {e}"

        # Foto cozum istatistikleri
        if neo_lower in ("foto istatistik", "foto cozum", "foto rapor", "foto stats"):
            try:
                from foto_solver_v2 import get_foto_stats, format_foto_stats
                stats = await get_foto_stats()
                return format_foto_stats(stats)
            except Exception as e:
                return f"Foto stats hatasi: {e}"

        # PDF Rapor: "rapor pdf [isim]" → admin'e PDF gonder
        if neo_lower.startswith(("rapor pdf ", "pdf rapor ", "rapor uret ", "rapor olustur ")):
            try:
                parts = text.split(" ", 2)
                if len(parts) < 3:
                    return "Kullanim: rapor pdf [ogrenci isim veya soz_no]"
                isim = parts[2].strip()

                if isim.isdigit():
                    soz_no = isim
                    row = await db_fetchrow("SELECT full_name FROM students WHERE soz_no::text=$1", soz_no)
                    name = row['full_name'] if row else f"Ogrenci #{soz_no}"
                else:
                    name_upper = isim.translate(str.maketrans("iığşüöç", "İIĞŞÜÖÇ")).upper()
                    row = await db_fetchrow(
                        "SELECT soz_no, full_name FROM students WHERE UPPER(full_name) ILIKE $1 LIMIT 1",
                        f"%{name_upper}%"
                    )
                    if not row:
                        return f"Ogrenci bulunamadi: {isim}"
                    soz_no = str(row['soz_no'])
                    name = row['full_name']

                from pdf_archive import get_archive_for_student
                pdf_path = await get_archive_for_student(soz_no)
                if not pdf_path:
                    return f"PDF olusturulamadi: {name}"

                # Admin'e gonder
                from datetime import date
                caption = f"📄 {name} — Akademik Rapor ({date.today().strftime('%d.%m.%Y')})"
                ok = await send_wa_document(phone, pdf_path, caption=caption)
                if ok:
                    return f"✅ PDF gonderildi: {name}"
                else:
                    return f"❌ PDF gonderim basarisiz, dosya hazir: {pdf_path}"
            except Exception as e:
                logger.error(f"Rapor PDF hatasi: {e}")
                return f"Rapor PDF hatasi: {e}"

        # Aylik arsiv: "aylik arsiv" / "aylik raporlar"
        if neo_lower in ("aylik arsiv", "aylık arşiv", "aylik raporlar", "aylık raporlar",
                         "ay arsivi", "ay arşivi", "rapor arsivi", "rapor arşivi"):
            try:
                from pdf_archive import generate_monthly_archive, format_archive_summary
                # Asenkron uretim — uzun surebilir
                await send_wa_message(phone, "📊 Aylik arsiv olusturuluyor... (~2-5dk)")
                sonuc = await generate_monthly_archive()
                return format_archive_summary(sonuc)
            except Exception as e:
                logger.error(f"Aylik arsiv hatasi: {e}")
                return f"Aylik arsiv hatasi: {e}"

        # Puan tahmin: "puan tahmin [isim]" / "puan tahmin [isim] [bolum]"
        if neo_lower.startswith(("puan tahmin ", "yks tahmin ", "puan analiz ", "tahmin et ")):
            try:
                from puan_tahmin import tahmin_et, hedef_analiz, format_rapor, BOLUM_HEDEFLER
                # "puan tahmin ecrin" veya "puan tahmin ecrin tip"
                parts = text.split()
                if len(parts) < 3:
                    return ("Kullanim: puan tahmin [isim] [opsiyonel_bolum]\n"
                            f"_Bolumler: {', '.join(list(BOLUM_HEDEFLER.keys())[:8])}_")
                # Son kelime bolum mi?
                bolum = None
                if parts[-1].lower() in BOLUM_HEDEFLER:
                    bolum = parts[-1].lower()
                    isim = " ".join(parts[2:-1])
                else:
                    isim = " ".join(parts[2:])

                # Isim → soz_no
                if isim.strip().isdigit():
                    soz_no = isim.strip()
                else:
                    name_upper = isim.translate(str.maketrans("iığşüöç", "İIĞŞÜÖÇ")).upper()
                    row = await db_fetchrow(
                        "SELECT soz_no FROM students WHERE UPPER(full_name) ILIKE $1 LIMIT 1",
                        f"%{name_upper}%"
                    )
                    if not row:
                        return f"Ogrenci bulunamadi: {isim}"
                    soz_no = str(row['soz_no'])

                tahmin = await tahmin_et(soz_no)
                hedef = None
                if bolum and bolum in BOLUM_HEDEFLER:
                    b = BOLUM_HEDEFLER[bolum]
                    hedef = hedef_analiz(tahmin, b['puan'], b['alan'])
                return format_rapor(tahmin, hedef)
            except Exception as e:
                logger.error(f"Puan tahmin hatasi: {e}")
                return f"Puan tahmin hatasi: {e}"

        # Akilli etut onerisi (kurum geneli)
        if neo_lower in ("etut oncelikleri", "etüt öncelikleri", "etut oner", "etüt öner",
                         "kurum etut", "kurum etüt", "etut acil", "etüt acil"):
            try:
                from smart_etut_advisor import get_kurum_etut_oncelikleri
                return await get_kurum_etut_oncelikleri(top=5)
            except Exception as e:
                logger.error(f"Etut onerisi hatasi: {e}")
                return f"Etut onerisi hatasi: {e}"

        # Akilli etut onerisi (ogrenci bazli): "etut oner [isim]" / "etüt öner [isim]"
        if neo_lower.startswith(("etut oner ", "etüt öner ", "etut onerisi ", "etüt önerisi ")):
            try:
                # "etut oner ecrin beller" → "ecrin beller"
                parts = text.split(" ", 2)
                if len(parts) < 3:
                    return "Kullanim: etut oner [ogrenci adi veya soz_no]"
                arg = parts[2].strip()

                # soz_no mu isim mi?
                if arg.isdigit():
                    soz_no = arg
                else:
                    # Isimle ara (TR-uppercase)
                    name_upper = arg.translate(str.maketrans("iığşüöç", "İIĞŞÜÖÇ")).upper()
                    row = await db_fetchrow(
                        "SELECT soz_no, full_name FROM students WHERE UPPER(full_name) ILIKE $1 LIMIT 1",
                        f"%{name_upper}%"
                    )
                    if not row:
                        return f"Ogrenci bulunamadi: {arg}"
                    soz_no = str(row['soz_no'])

                from smart_etut_advisor import recommend_etut_for_student
                return await recommend_etut_for_student(soz_no)
            except Exception as e:
                logger.error(f"Etut onerisi hatasi: {e}")
                return f"Etut onerisi hatasi: {e}"

        # Veri güncellik durumu — Oturum 25.29: yeni helper kullan (last_success
        # ile last_attempt ayri, last_error gosterir)
        if neo_lower in ("freshness", "guncellik", "veri durumu", "son sync"):
            try:
                from admin_sync_commands import get_freshness_report
                return await get_freshness_report()
            except Exception as e:
                return f"Hata: {e}"

        # Feedback triaj raporu (Oturum 25.29) — admin "feedback rapor"
        if neo_lower in ("feedback", "feedback rapor", "geri bildirim",
                          "geri bildirim rapor", "feedback durum", "feedback triaj"):
            try:
                from admin_sync_commands import get_feedback_triage_report
                return await get_feedback_triage_report()
            except Exception as e:
                return f"Hata: {e}"

        # Manuel triaj tetikle — admin "feedback triaj baslat"
        if neo_lower in ("feedback triaj baslat", "geri bildirim triaj"):
            try:
                from feedback_triage import triage_pending_feedback
                rep = await triage_pending_feedback(dry_run=False)
                return (
                    f"📋 Triaj tamamlandi:\n"
                    f"  Total: {rep.get('total', 0)}\n"
                    f"  Teknik: {rep['kategoriler'].get('teknik', 0)}\n"
                    f"  Icerik: {rep['kategoriler'].get('icerik', 0)}\n"
                    f"  Vague: {rep['kategoriler'].get('vague', 0)}\n"
                    f"  Saka: {rep['kategoriler'].get('saka', 0)}\n"
                    f"  Admin alert: {rep.get('alerted', 0)}"
                )
            except Exception as e:
                return f"Triaj hata: {e}"

        # Talimat kaydet: "talimat: ..." veya "not: ..." veya "ekle: ..."
        if neo_lower.startswith(("talimat:", "talimat ", "not:", "not ", "ekle:", "ekle ", "guncelle:", "guncelle ", "todo:", "todo ")):
            # "talimat: xyz" → "xyz" kısmını al
            talimat_text = text.split(":", 1)[-1].strip() if ":" in text else text.split(" ", 1)[-1].strip()
            if talimat_text:
                try:
                    # admin_talimat tablosu yoksa oluştur
                    await db_execute("""
                        CREATE TABLE IF NOT EXISTS admin_talimat (
                            id SERIAL PRIMARY KEY,
                            phone TEXT,
                            talimat TEXT,
                            durum TEXT DEFAULT 'bekliyor',
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)
                    await db_execute(
                        "INSERT INTO admin_talimat (phone, talimat) VALUES ($1, $2)",
                        phone, talimat_text)
                    count = await db_fetchval("SELECT COUNT(*) FROM admin_talimat WHERE durum='bekliyor'")
                    return f"Anlasildi efendim. Talimat kaydedildi.\n\n_Bekleyen talimat sayisi: {count}_"
                except Exception as e:
                    return f"Talimat kayit hatasi: {e}"
            return "Kullanim: talimat: buraya yazin"

        # Bekleyen talimatlar listesi
        if neo_lower in ("talimatlar", "talimat listesi", "bekleyen", "todolar"):
            try:
                rows = await db_fetch(
                    "SELECT id, talimat, to_char(created_at, 'DD.MM HH24:MI') as ts FROM admin_talimat WHERE durum='bekliyor' ORDER BY created_at")
                if not rows:
                    return "Bekleyen talimat yok."
                lines = [f"*Bekleyen Talimatlar ({len(rows)}):*\n"]
                for r in rows:
                    lines.append(f"  #{r['id']} [{r['ts']}] {r['talimat'][:80]}")
                return "\n".join(lines)
            except Exception as e:
                return f"Hata: {e}"

        # Haftalik trend
        if neo_lower in ("trend", "haftalik", "haftalık"):
            try:
                from usage_tracker import get_weekly_trend
                return await get_weekly_trend()
            except Exception as e:
                return f"Trend hatasi: {e}"

        # Sistem durumu
        if neo_lower in ("sistem", "durum", "neo durum"):
            from session_keeper import get_eyotek_status
            status = get_eyotek_status()
            blocked = 0
            try:
                blocked = await db_fetchval("SELECT COUNT(*) FROM blocked_numbers") or 0
                acl_counts = await db_fetch("SELECT role, COUNT(*) as c FROM acl_users WHERE is_active=TRUE GROUP BY role")
            except Exception:
                acl_counts = []

            lines = ["*FermatAI Sistem Durumu*\n",
                     f"Eyotek: {status.get('eyotek_session', '?')}",
                     f"Son kontrol: {status.get('last_check', '?')}",
                     f"Bloklu numaralar: {blocked}",
                     "\n*ACL Kayitlari:*"]
            for r in acl_counts:
                lines.append(f"  {r['role']}: {r['c']}")
            return "\n".join(lines)

        # 25.50 — Model sağlık komutu (vendor emekli erken tespit, qwen+llama8b vakası)
        if neo_lower in ("model durum", "model health", "model saglik", "model sağlık", "modeller"):
            try:
                from model_health import run_health_check, format_report
                summary = await run_health_check(alert=False)  # manuel — sessiz alarm (rapor zaten dönüyor)
                return format_report(summary)
            except Exception as _mh_e:
                return f"Model sağlık kontrolü hatası: {str(_mh_e)[:160]}"

    # 22.1m — Whisper ENTEGRE: text artik transcribe'dan geliyor, normal flow devam
    # Eski ses-bloklama kaldirildi. Sadece transcribe BAŞARISIZ ise (text "[SES MESAJI — anlasilamadi]"
    # gibi marker ise) yazili yonlendirmeye dus.
    if audio_bytes and text and text.startswith("[SES"):
        # Whisper hata (quota/key/bozuk ses) — kullaniciya bilgi
        if "bakiye yok" in text.lower():
            return (
                "🎤 Ses cozumu gecici kapali (sistem bakiye yenileniyor). "
                "Sorunuzu YAZILI gonderirseniz hemen cevaplayabilirim."
            )
        return (
            "Ses mesajini anlayamadim (gurultulu veya cok kisa olabilir). "
            "Sorunuzu yazili gonderir misiniz?"
        )

    if not text.strip():
        return "Mesajınızı anlayamadım. Lütfen tekrar deneyin."

    # ── 2. Özel komutlar ───────────────────────────────────────────────────────
    lower = text.strip().lower()

    # ── Admin sistem komutlari ────────────────────────────────────────────────
    # Oturum 25.4 Faz 2: Eyotek VPS auto-login komutlari
    if lower in ("eyotek baglan", "eyotek bağlan", "eyotek connect", "eyotek aç", "eyotek ac"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") == "admin":
            try:
                from eyotek_auto_login import eyotek_connect_command
                force = "zorla" in lower or "force" in lower
                return await eyotek_connect_command(force=force)
            except Exception as e:
                return f"❌ Eyotek baglanti hatasi: {e}"
        return "Bu komut sadece admin icin."

    if lower in ("eyotek durum", "eyotek status", "eyotek durumu"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            try:
                from eyotek_auto_login import eyotek_status_command
                return await eyotek_status_command()
            except Exception as e:
                return f"❌ Durum sorgu hatasi: {e}"
        return "Bu komut sadece yoneticiler icin."

    if lower in ("eyotek kapat", "eyotek disconnect", "eyotek kes"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") == "admin":
            try:
                from eyotek_auto_login import eyotek_disconnect_command
                return await eyotek_disconnect_command()
            except Exception as e:
                return f"❌ Kapatma hatasi: {e}"
        return "Bu komut sadece admin icin."

    # Eski "eyotek tamam" komutu (laptop CDP cookie refresh) — geriye dönük uyumlu
    if lower in ("eyotek tamam", "eyotek onayla", "session yenile"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            try:
                from eyotek_wrapper import get_session
                cookies = await get_session()
                if cookies:
                    return "✅ Eyotek session yenilendi (laptop CDP)."
                return (
                    "⚠️ Laptop CDP'den session alınamadı.\n\n"
                    "VPS otomatik login için: `eyotek baglan`"
                )
            except Exception as e:
                return f"Session yenileme hatasi: {e}"
        return "Bu komut sadece yoneticiler icin."

    if lower in ("token", "wa token", "token yenile"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") == "admin":
            try:
                new_token = await _refresh_wa_token()
                if new_token:
                    return "✅ *WA Token yenilendi!*\n\nYeni token aktif."
                return "⚠️ Token yenilenemedi. FB_APP_ID/SECRET kontrol edin."
            except Exception as e:
                return f"Token hatası: {e}"
        return "Bu komut sadece admin içindir."

    # Jarvis admin komutları (sadece Neo)
    if lower in ("jarvis", "brief", "gunaydin", "günaydın", "sabah") and phone == "905051256802":
        try:
            from jarvis_admin import build_neo_morning_brief
            return await build_neo_morning_brief()
        except Exception as _je:
            return f"Jarvis hatası: {_je}"
    if lower in ("sistem", "kendini anlat", "self report", "toplanti", "toplantı") and phone == "905051256802":
        try:
            from jarvis_admin import system_self_report
            return await system_self_report()
        except Exception as _se:
            return f"Self-report hatası: {_se}"

    # Email kaydet — herhangi bir kullanıcı "email: xxx@yyy.com" şeklinde gönderebilir
    # Calendar attendee olmak için kritik
    import re as _re_email
    _email_match = _re_email.match(r'^(email|e-mail|mail)[:\s]+(\S+@\S+\.\S+)\s*$', lower)
    if _email_match:
        from external_apis import set_user_email
        email = _email_match.group(2)
        ok = await set_user_email(phone, email)
        if ok:
            return (
                f"📧 Email kaydedildi: *{email}*\n\n"
                f"Artık çalışma planı veya etüt oluşturulduğunda "
                f"Google takvimine davet gönderilecek. Bir tıkla kendi takvimine ekleyebilirsin. 📅\n\n"
                f"_Değiştirmek istersen yine 'email: ...' yazabilirsin._"
            )
        else:
            return "❌ Email kaydedilemedi. Format: 'email: adresin@gmail.com'"

    # API status — Neo key ekledikten sonra kontrol
    if lower in ("api", "api durum", "api status", "keyler", "key status") and phone == "905051256802":
        try:
            from external_apis import status_report
            st = status_report()
            lines = ["🔑 *External API Durumu*", "━━━━━━━━━━━━━━━━━━━━━━"]
            emoji = {"youtube": "🎥", "google_calendar": "📅", "anthropic_files": "📂", "whisper": "🎙"}
            for k, v in st.items():
                ico = emoji.get(k, "•")
                status = "🟢 AKTIF" if v else "🔴 Key yok"
                lines.append(f"  {ico} *{k}*: {status}")
            lines.append("")
            lines.append("_Key setup: `SETUP_API_KEYS.md`_")
            return "\n".join(lines)
        except Exception as _ae:
            return f"API status hatası: {_ae}"

    # 23 Nisan — Tercih Robotu admin komutları (Neo only)
    if lower in ("tercih modu ac", "tercih modu aç", "tercih ac", "tercih aç") and phone == "905051256802":
        from tercih_robotu import set_tercih_modu
        result = await set_tercih_modu(True, admin_phone=phone)
        return f"🎯 {result}\n\n_Öğrenciler ve rehber tercih robotu modunda konuşacak._"

    if lower in ("tercih modu kapa", "tercih modu kapat", "tercih kapa", "tercih kapat") and phone == "905051256802":
        from tercih_robotu import set_tercih_modu
        result = await set_tercih_modu(False, admin_phone=phone)
        return f"🎯 {result}"

    if lower in ("tercih durum", "tercih durumu", "tercih modu durum"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur", "rehber"):
            from tercih_robotu import tercih_donemi_durum
            d = await tercih_donemi_durum()
            lines = [
                f"🎯 *Tercih Robotu — {'AKTIF ✅' if d['tercih_modu_aktif'] else 'KAPALI ⏸'}*",
                f"Bugün: {d['bugun']}",
                "",
                "*Timeline:*",
            ]
            for t in d["timeline"]:
                if t["gecti_mi"]:
                    lines.append(f"  ✓ {t['olay']} ({t['tarih']}) — {abs(t['kaldi_gun'])} gün önce")
                else:
                    lines.append(f"  ⏳ {t['olay']} ({t['tarih']}) — {t['kaldi_gun']} gün sonra")
            lines.append("")
            lines.append(f"_{d['mesaj']}_")
            return "\n".join(lines)
        return "Bu komut için yetkin yok."

    if lower in ("sistem durum", "sistem durumu", "status"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            from session_keeper import get_eyotek_status
            status = get_eyotek_status()
            eyotek = status.get("eyotek_session", "bilinmiyor")
            last = status.get("last_check", "?")
            uptime = status.get("uptime_start", "?")
            return (
                f"*FermatAI Sistem Durumu*\n\n"
                f"Eyotek: {eyotek}\n"
                f"Son kontrol: {last}\n"
                f"Uptime: {uptime}\n"
                f"WP Bridge: aktif"
            )
        return "Bu komut sadece yoneticiler icin."

    if lower in ("sync baslat", "veri guncelle", "güncelle", "guncelle"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            try:
                from admin_sync_commands import get_update_checklist
                return await get_update_checklist()
            except Exception as e:
                return f"Güncelleme kontrol hatası: {e}"
        return "Bu komut sadece yoneticiler icin."

    # 22.1n-neo: FINANS sync (SADECE Neo) — 3 sezon
    if lower in ("finans sync", "finans guncelle", "finans güncelle",
                 "finans sync dry", "finans test",
                 "3 sezon sync", "sezon sync"):
        from finans_access import is_finans_authorized
        if not is_finans_authorized(phone):
            return "Finansal veri senkronu sadece kurum sahibi icindir."
        try:
            dry = "dry" in lower or "test" in lower
            from finans_eyotek_reader import sync_all_seasons
            report = await sync_all_seasons(dry_run=dry)
            mode = "DRY-RUN (yazma yok)" if dry else "GERCEK SYNC (3 sezon)"
            lines = [f"*Finans Sync — {mode}*\n"]
            for sezon, data in report.get("sezonlar", {}).items():
                okuma = data.get("okuma", {})
                yazma = data.get("yazma", {})
                lines.append(f"*{sezon}*")
                lines.append(f"  Bilanco: {yazma.get('bilanco', okuma.get('bilanco', 0))} | "
                             f"Geciken: {yazma.get('geciken', okuma.get('geciken', 0))} | "
                             f"Ogrenci: {yazma.get('ogrenci_odeme', okuma.get('ogrenci_odeme', 0))}")
            kiyas = report.get("kiyaslama", {})
            if kiyas:
                lines.append("\n*Kiyaslama:*")
                for s, k in kiyas.items():
                    buy = f" ({k['buyume_pct']:+.1f}%)" if "buyume_pct" in k else ""
                    lines.append(f"  {s}: Ciro {k.get('ciro', 0):,.0f} TL{buy}")
            return "\n".join(lines)
        except Exception as e:
            return f"Finans sync hatasi: {e}"

    # 22.1n-neo: FINANS kiyasla kisa yol
    if lower in ("finans kiyas", "finans karsilas", "sezon kiyas", "3 sezon"):
        from finans_access import is_finans_authorized
        if not is_finans_authorized(phone):
            return "Sadece kurum sahibi erisebilir."
        try:
            from finans_tools import sezon_kiyasla
            r = await sezon_kiyasla(_caller_phone=phone)
            if not r.get("basarili"):
                return r.get("error", "Veri yok")
            lines = ["*📊 3 Sezon Finansal Kiyaslama*\n"]
            for s in r.get("sezonlar", []):
                lines.append(f"*{s['sezon']}*")
                lines.append(f"  Ogrenci: {s['ogrenci_sayisi']} | Ort fiyat: {s.get('ort_kayit_fiyati', 0):,.0f} TL")
                lines.append(f"  Ciro: {s.get('toplam_taksit', 0):,.0f} | Tahsilat: {s.get('toplam_tahsilat', 0):,.0f} TL (%{s.get('tahsilat_oran_pct', 0)})")
                lines.append(f"  Kalan: {s.get('toplam_kalan', 0):,.0f} TL\n")
            for b in r.get("buyume_analizi", []):
                lines.append(f"*{b['donem']}:* {b['kayit_buyume_pct']:+.1f}% ({b['kayit_fark_tl']:+,.0f} TL, +{b['ogrenci_fark']} ogr)")
            return "\n".join(lines)
        except Exception as e:
            return f"Kiyaslama hatasi: {e}"

    # 22.1n-neo: Aylik borc
    import re as _re_borc
    m_borc = _re_borc.match(r"^(?:aylik borc|bu ay borc|kim borclu|geciken|borclu listesi)\s*(\d{4}-\d{2})?\s*$", lower)
    if m_borc:
        from finans_access import is_finans_authorized
        if not is_finans_authorized(phone):
            return "Sadece kurum sahibi erisebilir."
        try:
            ay = m_borc.group(1) or ""
            from finans_tools import aylik_borc_detay
            r = await aylik_borc_detay(ay=ay, _caller_phone=phone)
            if not r.get("basarili"):
                return r.get("error", "Veri yok")
            lines = [f"*💰 Geciken Borclular {'— ' + ay if ay else '— Tum aylar'}*\n"]
            for row in r.get("aylik_ozet", []):
                lines.append(f"*{row['ay']}:* {row['ogrenci_sayisi']} ogrenci, toplam *{float(row['toplam_borc']):,.0f} TL*")
            if r.get("ogrenci_detay"):
                lines.append("\n*Detay:*")
                for d in r["ogrenci_detay"][:20]:
                    lines.append(f"  • {d['full_name']} ({d['soz_no']}) *{float(d['borc']):,.0f} TL*")
            return "\n".join(lines)
        except Exception as e:
            return f"Aylik borc hatasi: {e}"

    if lower in ("son güncelleme", "son guncelleme", "sync durumu", "sync durum"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            try:
                from admin_sync_commands import get_sync_status
                return await get_sync_status()
            except Exception as e:
                return f"Sync durum hatası: {e}"
        return "Bu komut sadece yoneticiler icin."

    # Eyotek -> DB son sinav sync raporu (Oturum 25.29)
    if lower in ("son sinav sync", "son sınav sync", "eyotek sync",
                 "sinav sync", "sınav sync", "son ingest"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur"):
            try:
                from admin_sync_commands import get_last_eyotek_sync
                return await get_last_eyotek_sync()
            except Exception as e:
                return f"Sync log okunamadı: {e}"
        return "Bu komut sadece yoneticiler icin."

    # Anlik sync tetikle — admin only (Oturum 25.29)
    if lower in ("sinav sync baslat", "sınav sync başlat",
                 "eyotek sync baslat", "yeni sinavlari cek", "yeni sınavları çek"):
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") not in ("admin",):
            return "Bu komut sadece admin icin."
        # Background tetikle, anlik cevap don
        async def _bg_sync():
            try:
                from sync_recent_exams import sync_recent_exams
                rep = await sync_recent_exams(
                    days=30, dry_run=False, trigger="manual_wp", max_exams_per_run=5
                )
                logger.info(f"[WP] Manuel sync: {rep.get('exams_new', 0)} yeni, "
                            f"{rep.get('rows_inserted', 0)} satir")
            except Exception as e:
                logger.exception(f"[WP] Manuel sync fail: {e}")
        asyncio.create_task(_bg_sync())
        return ("⏳ Sinav sync arka planda baslatildi.\n"
                "_Sonuc icin: `son sinav sync`_")

    # "güncelle [isim]" — tek öğrenci veri güncelliği kontrolü
    if lower.startswith(("güncelle ", "guncelle ")) and len(lower) > 10:
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        if prof.get("role") in ("admin", "mudur", "rehber"):
            student_name = lower.replace("güncelle ", "").replace("guncelle ", "").strip()
            if student_name and student_name not in ("etut", "etüt", "sinav", "sınav"):
                try:
                    from admin_sync_commands import get_student_freshness
                    return await get_student_freshness(student_name)
                except Exception as e:
                    return f"Öğrenci kontrol hatası: {e}"

    # ── MESAJ GÖNDERME — "ilet/gönder [kişi]" ──
    # Pending mesaj varsa onay/iptal kontrolü
    _pending_send_key = f"pending_send_{phone}"
    _pending_sends = getattr(process_message, '_pending_sends', {})

    if _pending_send_key in _pending_sends and lower in ("onayla", "onaylıyorum", "evet", "gonder", "gönder"):
        pending = _pending_sends.pop(_pending_send_key)
        process_message._pending_sends = _pending_sends
        try:
            from secure_messenger import send_wp_message, log_sent_message
            success = await send_wp_message(pending['phone'], pending['message'])
            if success:
                await log_sent_message(phone, pending['recipient'], pending['message'], True)
                return f"✅ *Mesaj gönderildi!*\n\nAlıcı: *{pending['recipient']['name']}*"
            else:
                return "⚠️ Mesaj gönderilemedi. WA token kontrol edilmeli."
        except Exception as e:
            return f"⚠️ Gönderim hatası: {e}"

    if _pending_send_key in _pending_sends and lower in ("iptal", "vazgec", "vazgeç", "hayır"):
        _pending_sends.pop(_pending_send_key)
        process_message._pending_sends = _pending_sends
        return "❌ Mesaj gönderimi iptal edildi."

    if lower in ("sıfırla", "reset", "/reset", "temizle"):
        if phone in _AGENT_SESSIONS:
            _AGENT_SESSIONS[phone].reset()
        # Bekleyen followup durumunu da temizle
        _PENDING_FOLLOWUP.pop(phone, None)
        _PENDING_SPLIT.pop(phone, None)
        return "✅ Konuşma geçmişi temizlendi."

    # ── Split continuation: "devam / devami / yarim kaldi / kesildi" → 2. parcayi tekrar gonder ─
    if phone in _PENDING_SPLIT and lower in (
        "devam", "devamı", "devami", "devamini", "devamını",
        "yarım kaldı", "yarim kaldi", "kesildi", "eksik", "gelmedi"
    ):
        split_info = _PENDING_SPLIT.pop(phone, None)
        if split_info and split_info.get("full_response"):
            return f"_Tüm mesajı tekrar gönderiyorum:_\n\n{split_info['full_response']}"

    if lower in ("yardım", "help", "/help"):
        # 25.43-ACL-LEAK FIX (Neo iter#2 judge tespit):
        # Eski kod: tüm non-ogrenci rollere ADMIN KOMUT LISTESI veriyordu —
        # veli "yardım" deyince 'Etut: 11 SAY A'ya fizik etut yaz' görüyordu (ACL ihlali).
        # Rol-bazlı yardım: admin/mudur admin komutları, ogretmen/rehber kendi,
        # veli/guest sadece tanıtım, ogrenci akademik.
        from fermat_core_agent import _get_caller_profile
        prof = await _get_caller_profile(phone)
        role = prof.get("role", "unknown")
        name = prof.get("full_name") or prof.get("first_name") or ""
        greeting = f"Merhaba {name}! " if name else ""

        if role == "ogrenci":
            return (
                f"{greeting}*FermatAI Ogrenci Asistani*\n\n"
                "Bana su konularda sorabilirsin:\n"
                "- Derslerimle ilgili sorular\n"
                "- Devamsizlik durumum\n"
                "- Sinav sonuclarim\n"
                "- Akademik destek (foto ile soru atabilirsin!)\n\n"
                "Sifirlamak icin: *sifirla*"
            )
        elif role == "ogretmen":
            return (
                f"{greeting}*FermatAI Ogretmen Asistani*\n\n"
                "Size yardimci olabilecegim alanlar:\n"
                "- Sinifimin son deneme ozeti\n"
                "- Zayif konu haritasi (sinif bazli)\n"
                "- Bu hafta ders programim\n"
                "- Etut istatistiklerim\n"
                "- Brans onerisi yazma (rehbere)\n\n"
                "Sifirlamak icin: *sifirla*"
            )
        elif role == "rehber":
            return (
                f"{greeting}*FermatAI Rehberlik Asistani*\n\n"
                "Size yardimci olabilecegim alanlar:\n"
                "- Negatif duygu sinyali alan ogrenciler\n"
                "- Ogrenci duygu durumu\n"
                "- Brans ogretmeni etut onerileri\n"
                "- Rehberlik notu ekleme\n"
                "- Risk altinda ogrenci listesi\n\n"
                "Sifirlamak icin: *sifirla*"
            )
        elif role in ("admin", "mudur", "yonetim"):
            return (
                f"{greeting}*FermatAI Yonetim Komutlari*\n\n"
                "Rapor: 'Ahmet'i raporla'\n"
                "Etut: '11 SAY A'ya fizik etut yaz'\n"
                "Not: 'Ali icin rehberlik notu ekle'\n"
                "Sinif: '11 SAY A'nin durumu nasil'\n"
                "Devamsiz: 'Bugun kimler gelmedi'\n\n"
                "Sifirlamak icin: *sifirla*"
            )
        elif role == "veli":
            return (
                f"{greeting}*FermatAI — Veli Asistani* 👨‍👩‍👧\n\n"
                "Size yardımcı olabileceğim alanlar:\n"
                "• 📊 *Çocuğumun durumu* — son deneme + akademik özet\n"
                "• 📅 *Haftalık rapor* — sınav + devamsızlık özeti\n"
                "• 🤝 *Randevu iste* — rehber/öğretmen görüşme\n"
                "• 📞 *İletişim* — kurum çağrı hattı\n\n"
                "_Yazılı sorabilirsiniz, ben yönlendiririm._\n\n"
                "Acil: *0546 260 54 46*"
            )
        else:  # guest, unknown
            return (
                f"{greeting}*FermatAI — Fermat Egitim Kurumlari Asistani*\n\n"
                "Akademik destek icin Fermat'a kayitli olmaniz gerekir.\n"
                "Kayit icin: 0546 260 54 46\n"
                "Web: fermategitimkurumlari.com"
            )

    # ── 3. HIZLI YANIT — Intent parser'dan ONCE, en hizli yol ─────────────────
    try:
        from fast_responses import try_fast_response
        profile = await _is_phone_registered(phone)
        logger.info(f"  [WP-FAST] Profil: {profile.get('role') if profile else 'None'}")
        if profile:
            _soz = None
            try:
                _soz = int(profile.get("soz_no") or profile.get("eyotek_id") or 0) or None
            except (ValueError, TypeError):
                pass
            # 25.41 (Neo bug 7 May): ACL profile soz_no içermiyor, sadece
            # eyotek_id var. Mehmet Ali Karpuz "ben kimim" → soz_no None →
            # zengin handler bypass → kısa cevap. Çare: students'ten direkt çek.
            if not _soz and profile.get("phone"):
                try:
                    from db_pool import db_fetchval as _dfv_soz
                    _phone_clean = profile["phone"].replace("+", "").strip()
                    _soz_lookup = await _dfv_soz(
                        "SELECT soz_no FROM students WHERE REPLACE(phone,'+','')=$1 LIMIT 1",
                        _phone_clean,
                    )
                    if _soz_lookup:
                        _soz = int(_soz_lookup) if str(_soz_lookup).isdigit() else None
                except Exception:
                    pass
            fast = await try_fast_response(
                message=text,
                caller_phone=phone,
                role=profile.get("role", "unknown"),
                soz_no=_soz,
                name=profile.get("full_name", ""),
                staff_name=profile.get("full_name", "") if profile.get("role") in ("ogretmen", "rehber") else "",
                channel=channel,  # 25.46+ kanal-aware fast_response (satranç guard'i web'de URL eklemiyor)
            )
            if fast:
                logger.info(f"  [WP-FAST] Aninda yanitlandi (<100ms)")
                logger.info(f"  [WP-FAST] Soru: {text[:80]}")
                logger.info(f"  [WP-FAST] Yanit: {fast[:100]}")
                # 25.41 (Neo) — ANTI-REPEAT GUARD: handler'i kaydet (sonraki mesaj kontrol icin)
                try:
                    from fast_responses import get_last_handler as _glh_rec
                    from fast_response_loop_guard import record_handler
                    _hh = _glh_rec()
                    if _hh:
                        record_handler(phone, _hh, text)
                except Exception:
                    pass
                # Agent history'sine ekle — bağlam koruması için
                try:
                    _agent = get_agent(phone)
                    if _agent and hasattr(_agent, 'history'):
                        _agent.history.append({"role": "user", "content": text})
                        _agent.history.append({"role": "assistant", "content": fast})
                except Exception:
                    pass
                # DB'ye konuşma kaydet — TEST MODE değilse
                try:
                    _role = profile.get("role", "")
                    _name = profile.get("full_name", "")
                    _agent = get_agent(phone)
                    if _agent and not _is_test_mode():
                        _pool_fast = await get_db_pool()
                        async with _pool_fast.acquire() as _conn:
                            _sid = _agent.session_id if hasattr(_agent, 'session_id') else "fast"
                            await _conn.execute(
                                "INSERT INTO agent_conversations (session_id, phone, role, message_role, content) VALUES ($1,$2,$3,$4,$5)",
                                _sid, phone, _role, "user", text)
                            await _conn.execute(
                                "INSERT INTO agent_conversations (session_id, phone, role, message_role, content, tools_used) VALUES ($1,$2,$3,$4,$5,$6)",
                                _sid, phone, _role, "assistant", fast, ["fast_response"])
                            # 22.1n-neo: handler_name takibi (bos ise None)
                            try:
                                from fast_responses import get_last_handler as _glh
                                _hname = _glh() or None
                            except Exception:
                                _hname = None
                            # 25.42 (Bulgu F): test_user flag — Neo testi vs gercek kullanici ayrimi
                            try:
                                from test_user_registry import is_test_phone as _is_test_p
                                _is_test = _is_test_p(phone)
                            except Exception:
                                _is_test = False
                            await _conn.execute(
                                "INSERT INTO routing_stats (phone, role, message, response_source, response_ms, handler_name, is_test_user) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                                phone, profile.get("role",""), text[:200], "fast_response", 5, _hname, _is_test)
                except Exception as _e:
                    logger.debug(f"  Fast DB log hatasi: {_e}")
                # Usage log
                try:
                    from usage_tracker import log_event
                    await log_event(phone=phone, role=profile.get("role",""), full_name=profile.get("full_name",""),
                                    event_type="message", response_source="fast_response", response_ms=5)
                except Exception:
                    pass
                # ── GÖRSEL ENFORCER — fast response de Claude standardında çıksın ──
                try:
                    from format_whatsapp import format_for_whatsapp
                    fast = format_for_whatsapp(fast, source="fast")
                except Exception:
                    pass
                # ── Admin self-awareness footer — Neo route'unu bilsin ──
                if phone == "905051256802":
                    fast = fast + "\n\n_⚙ via *fast_response* · ~5ms_"
                return fast
            else:
                # routing_engine danışmanlık — context-dependent mesajları Claude'a yönlendir
                try:
                    from routing_engine import decide_route
                    _pre_route = decide_route(text, profile.get("role", ""), phone)
                    if _pre_route == "claude":
                        logger.info(f"  [WP-ROUTING] routing_engine → claude (fast atlandı)")
                    elif _pre_route == "fast":
                        logger.info(f"  [WP-ROUTING] routing_engine → fast ama pattern yok, agent'a")
                    else:
                        logger.info(f"  [WP-FAST] Pattern bulunamadi, agent'a gidiyor")
                except Exception:
                    logger.info(f"  [WP-FAST] Pattern bulunamadi, agent'a gidiyor")
    except Exception as e:
        logger.warning(f"  WP fast response HATA: {e}")

    # ── 4. Bekleyen followup varsa cevabı birleştir ────────────────────────────
    pending = _PENDING_FOLLOWUP.pop(phone, None)
    if pending:
        # Tip kontrolü — sadece string kabul et (dict ise 13:58 bug'ı gibi payload leak olur)
        if isinstance(pending, str) and pending.strip():
            text = f"{pending} {text}"
            logger.info(f"Followup birlestirildi: {text[:80]}")
        else:
            logger.warning(f"_PENDING_FOLLOWUP beklenmeyen tip ({type(pending).__name__}), atlandi")

    # ── 5. Intent analizi (sadece yazma komutlari icin gerekli) ───────────────
    agent = get_agent(phone)
    if not agent:
        return "Su anda yogun bir donemden geciyoruz. Biraz sonra tekrar yazabilir misiniz? Yardimci olmak icin buradayim."

    # 25.41 (Brief #18): Lazy history yükleme — get_agent() artık ThreadPoolExecutor
    # kullanmıyor, history burada async olarak yüklenir (mevcut event loop, pool stabil).
    if getattr(agent, '_needs_history_load', False):
        try:
            from db_pool import db_fetch as _db_fetch_h
            rows = await _db_fetch_h("""
                SELECT message_role, content FROM agent_conversations
                WHERE phone = $1 AND message_role IN ('user','assistant')
                  AND content NOT LIKE '[tool_calls%'
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC LIMIT 10
            """, phone)
            if rows:
                for r in reversed(rows):
                    agent.history.append({
                        "role": r['message_role'] if r['message_role'] != 'assistant' else 'assistant',
                        "content": r['content']
                    })
                logger.info(f"  Baglam yuklendi (lazy): {len(rows)} mesaj")
            agent._needs_history_load = False
        except Exception as _h_err:
            logger.debug(f"  Baglam lazy load hatasi (devam): {_h_err}")
            agent._needs_history_load = False  # Tekrar denemeye gerek yok

    # Intent parser sadece yazma komutlari icin calistir (yaz, ekle, gonder)
    _WRITE_KEYWORDS = ["yaz", "ekle", "gonder", "gönder", "kaydet", "planla", "sms"]
    _needs_intent = any(kw in text.lower() for kw in _WRITE_KEYWORDS)

    try:
        if _needs_intent:
            from intent_parser import parse_intent
            intent = await parse_intent(text, use_llm=False)  # Ollama KULLANMA, sadece kural tabanlı
        else:
            intent = None

        if not intent:
            # Yazma komutu degil veya intent parser basarisiz → 5b'ye (watchdog + filler) devam et
            # 19 Nisan FIX: intent None ise dummy olustur — crash giderildi (157/24h)
            from types import SimpleNamespace
            intent = SimpleNamespace(action_type="UNKNOWN", entities={}, raw_text=text)

        # Followup: sadece kritik bilgi TAMAMEN eksikse sor.
        # WRITE_ETUT  → öğrenci/sınıf VEYA ders ikisi birden yoksa
        # WRITE_NOTE  → öğrenci adı yoksa
        # SEND_SMS    → hedef (sınıf/öğrenci) VE mesaj metni yoksa
        e = intent.entities
        needs_followup = False
        if intent.action_type == "WRITE_ETUT":
            has_target  = bool(e.get("student_name") or e.get("class_name") or e.get("student_id"))
            has_subject = bool(e.get("subject"))
            needs_followup = not (has_target and has_subject)
        elif intent.action_type == "WRITE_NOTE":
            needs_followup = not bool(e.get("student_name") or e.get("student_id"))
        elif intent.action_type == "SEND_SMS":
            has_target  = bool(e.get("class_name") or e.get("student_name"))
            has_message = bool(e.get("sms_message"))
            needs_followup = not (has_target and has_message)

        if (needs_followup
                and intent.followup_question
                and not pending):
            _PENDING_FOLLOWUP[phone] = text
            logger.info(f"❓ Followup [{phone}]: {intent.followup_question}")
            return intent.followup_question

    except Exception as e:
        logger.warning(f"Intent analizi başarısız, agent'a doğrudan gönderiliyor: {e}")

    # ── 5. Günlük Claude limit kontrolü ─────────────────────────────────────────
    DAILY_CLAUDE_LIMIT = 300  # Günlük max Claude çağrısı — $4-5 max WP maliyeti
    try:
        # Oturum 18: pool kullan (~50ms tasarruf / mesaj)
        _pool_lim = await get_db_pool()
        async with _pool_lim.acquire() as _conn_lim:
            _today_claude = await _conn_lim.fetchval(
                "SELECT COUNT(*) FROM agent_conversations WHERE message_role='assistant' "
                "AND tools_used::text = '{}' AND created_at >= CURRENT_DATE")

        if _today_claude and _today_claude >= DAILY_CLAUDE_LIMIT:
            logger.warning(f"  GUNLUK CLAUDE LIMITI ASILDI: {_today_claude}/{DAILY_CLAUDE_LIMIT}")
            # Limit aşıldıysa sadece Ollama ile cevapla
            try:
                answer = agent.router.chat_local(
                    messages=[{"role": "user", "content": text}],
                    system=agent.router._LOCAL_SYSTEM + f"\nArayan: {profile.get('full_name','')}\nRol: {profile.get('role','')}"
                )
                from fermat_core_agent import _fix_ollama_name
                answer = _fix_ollama_name(answer, profile.get('full_name',''), profile.get('role',''))
                return answer
            except Exception:
                return "Su anda yogun bir donem geciriyoruz. Biraz sonra tekrar yazabilir misiniz?"
    except Exception:
        pass

    # ── 5b. Agent'a gönder (timeout korumalı + filler watchdog) ──────────────────
    # UX: WhatsApp'ta "yazıyor..." göstergesi olmadığı için uzun analizlerde
    # 3sn'den fazla süren çağrılarda filler mesaj at.
    # KRITIK: channel="web" ise filler WP'YA GÖNDERİLMEZ — web kanalında
    # streaming thinking placeholder zaten var, WP'ya spam etmeyiz.
    try:
        import time as _time
        _agent_start = _time.time()

        # ═══════════════════════════════════════════════════════════════════
        # CLASSROOM MANAGEMENT — Token budget aşıldıysa Claude'a GITMEZ
        # (Neo 22 Nisan vizyonu — "sonsuz token masrafı önle")
        # Sadece ogrenci icin, ENFORCE_ACTIVE=true gerekli (default false).
        # ═══════════════════════════════════════════════════════════════════
        try:
            _cm_role = (profile or {}).get("role", "") if profile else ""
            if _cm_role == "ogrenci" and channel == "whatsapp":
                from token_budget import check_budget as _cm_check
                _cm_budget = await _cm_check(phone, _cm_role)
                if _cm_budget.get("enforce"):
                    from redirect_templates import get_budget_closing as _cm_closing
                    _cm_name = (profile or {}).get("full_name", "")
                    _cm_msg = _cm_closing("exceeded", _cm_name)
                    if _cm_msg:
                        await send_wa_message(phone, _cm_msg)
                        logger.info(f"  [CLASSROOM_MGMT] phone={phone[-4:]} budget EXCEEDED — Claude skip")
                        return
        except Exception as _cm_budget_e:
            logger.debug(f"  classroom budget check hata: {_cm_budget_e}")

        # 22.1n-neo Fikir 4: Claude burst koruma — aynı kullanıcı 60sn'de 3+ Claude
        # cagrisindaysa bu mesaj Claude'a GITMEZ, direkt "sabir" cevabi
        try:
            if is_claude_burst(phone) and channel == "whatsapp":
                burst_msg = claude_burst_message(phone)
                await send_wa_message(phone, burst_msg)
                logger.info(f"  [BURST_LIMIT] phone={phone[-4:]} Claude cagrisi atlandi")
                # Audit — TEST MODE değilse
                try:
                    if not _is_test_mode():
                        _pool_brst = await get_db_pool()
                        async with _pool_brst.acquire() as _cb:
                            try:
                                from test_user_registry import is_test_phone as _is_test_p
                                _is_test_b = _is_test_p(phone)
                            except Exception:
                                _is_test_b = False
                            await _cb.execute(
                                "INSERT INTO routing_stats (phone, role, message, response_source, response_ms, handler_name, is_test_user) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                                phone, profile.get("role","") if profile else "", text[:200],
                                "burst_limit", 0, "claude_burst_skip", _is_test_b
                            )
                except Exception as _brst_audit_e:
                    logger.debug(f"  burst audit yazim hatasi: {_brst_audit_e}")
                return
        except Exception as _brst_chk_e:
            logger.debug(f"  burst check hatasi: {_brst_chk_e}")

        # Long-intent tespit (web'de de loglama için lazım)
        try:
            from conversation_flow import (
                detect_long_intent, send_pre_filler, send_progress_after, get_post_followup
            )
            long_intent = detect_long_intent(text)
            logger.info(f"  [WATCHDOG] long_intent={long_intent} channel={channel}")
        except Exception as _flow_err:
            logger.error(f"  [WATCHDOG] conversation_flow import HATA: {_flow_err}")
            long_intent = None
        cancel_token = asyncio.Event()
        filler_sent = False
        progress_task = None

        # ── KANAL FARKINDALIĞI ── SADECE channel='whatsapp' WHEN WP'ya filler gönder
        # 25.37 (Neo bug 1 May): /agent endpoint default 'whatsapp' bırakıyordu → spam filler
        # Whitelist defense: channel literal 'whatsapp' OLMALI (web/agent_api/cli/test → WP YOK)
        _use_wa_filler = (channel == "whatsapp")
        if _use_wa_filler:
            logger.info(f"  [WATCHDOG] WP filler aktif (channel={channel})")
        else:
            logger.info(f"  [WATCHDOG] Filler KAPALI (channel={channel}, WP'ya mesaj atilmaz)")

        async def _watchdog():
            """3sn'de cevap yoksa filler at, 12sn'de progress at. (Sadece WP kanalı)"""
            nonlocal filler_sent, progress_task
            try:
                # 3sn bekle
                logger.info(f"  [WATCHDOG] 3sn bekleme basladi (phone={phone[-4:]} ch={channel})")
                await asyncio.wait_for(cancel_token.wait(), timeout=3.0)
                logger.info(f"  [WATCHDOG] cevap geldi (3sn'den once)")
                return  # cevap gelmiş, filler atma
            except asyncio.TimeoutError:
                logger.info(f"  [WATCHDOG] 3sn doldu, filler atilacak (wa={_use_wa_filler})")

            # Web kanalı → filler WP'ya GİTMESİN
            if not _use_wa_filler:
                logger.info(f"  [WATCHDOG] Web kanali, WP'ya filler atilmayacak")
                return

            # 3sn geçti, hala yok → filler at (sadece WP)
            try:
                if long_intent:
                    sent_ok = await send_pre_filler(
                        phone, long_intent,
                        name=profile.get('full_name', '') if profile else '',
                        send_func=send_wa_message,
                        delay_before=0,
                    )
                else:
                    # Generic filler (uzun-intent değilse de >3sn sürdüyse)
                    sent_ok = await send_pre_filler(
                        phone, {'intent': '_generic'},
                        name=profile.get('full_name', '') if profile else '',
                        send_func=send_wa_message,
                        delay_before=0,
                    )
                filler_sent = True
                logger.info(f"  [WATCHDOG] Filler atildi (ok={sent_ok})")
            except Exception as _fe:
                logger.error(f"  [WATCHDOG] Filler atma HATA: {_fe}")

            # 12sn sonra hala yoksa progress mesajı
            progress_task = asyncio.create_task(
                send_progress_after(phone, delay_sn=12.0,
                                    cancel_token=cancel_token,
                                    send_func=send_wa_message)
            )
            # 22.1n-neo fikir1: 30sn sonra 2. asama progress ("hala calisiyorum")
            try:
                from conversation_flow import send_progress_after_long
                progress_long_task = asyncio.create_task(
                    send_progress_after_long(phone, delay_sn=30.0,
                                              cancel_token=cancel_token,
                                              send_func=send_wa_message)
                )
            except Exception:
                pass

        watchdog_task = asyncio.create_task(_watchdog())
        # Watchdog task'ina bir tur yield et — event loop ona zaman versin
        await asyncio.sleep(0)

        # 22.1n-neo Fikir 4: Claude call tracking (burst detection icin)
        try:
            track_claude_call(phone)
        except Exception as _tc_e:
            logger.debug(f"  track_claude_call hatasi: {_tc_e}")

        try:
            # Oturum 23 (Neo timeout analizi): Kanala göre timeout.
            # Web UI streaming gösterdiği için kullanıcı beklemeye hazır,
            # uzun pedagojik rapor + multi-tool chain için 180s gerekli.
            # WhatsApp'ta fazla bekleme bad UX → 90s (eski 75s yetmedi).
            # Oturum 25.31 — Neo timeout raporu: kompleks render + history birikimi 180s asildi
            # Web kanalinda Claude reasoning + tool-calling icin 300s makul
            # Oturum 25.39 — Neo "yıldız doğumu/ölümü" 300s aşıldı; kompleks render
            # tespit edilirse 480s (max_tokens 24K + retry için). Cache aktif olduğu
            # için ortalama latency düşecek, sadece çok kompleks render bu süreyi kullanır.
            _is_complex_render = bool(re.search(
                r'\b(simülasyon|simulasyon|sim[üu]le|3d.*?(göster|olu[sş]tur)|'
                r'animasyon|interaktif|olu[sş]tur.*?simul|y[ıi]ld[ıi]z.*?evrim|'
                r'galak[sş]i|kuantum.*sim|kara.*delik|f[oö]toelektrik|'
                r'compton|dalga.*g[iı]ri[sş]im)',
                (text or "").lower(),
            ))
            # 25.44-dev-meeting-5: expand_row_details Eyotek tool'u uzun surer
            # (8-10 etut x 2sn popup = ekstra 20sn). "kim katiliyor / hangi ogrenci"
            # gibi sorgular tetikler. Bot agent_api 90s'i ASIYOR — bu admin/dev path.
            _q = (text or "").lower()
            _is_etut_expand = (
                ("etut" in _q or "etüt" in _q) and
                any(t in _q for t in (
                    "kim katiliyor", "kim katılıyor", "hangi ogrenci",
                    "hangi öğrenci", "ogrenci listesi", "öğrenci listesi",
                    "kimler katiliyor", "kimler katılıyor", "katilimci", "katılımcı",
                ))
            )
            # 25.46+ (Neo 18 May): admin/mudur/yonetim icin timeout gevsetmesi.
            # Neo: "benimle konusmalarda gevset cunku cok iyi isler cikariyor"
            # Tipik Neo seansi: kompleks pedagojik aciklama + multi-tool +
            # ardisik render denemeleri. 5dk web limiti yetersiz kaliyordu.
            # Yeni hedef (premium pool — admin/mudur/yonetim):
            #   web:        normal 600s / kompleks_render 900s (eski 300/480)
            #   agent_api:  normal 300s / kompleks 480s (eski 150/240)
            #   whatsapp:   normal 150s / kompleks 240s (eski 90/120)
            _premium_role = False
            try:
                _r = (profile or {}).get("role", "") if profile else ""
                _premium_role = _r in ("admin", "mudur", "yonetim")
            except Exception:
                _premium_role = False

            if channel == "web":
                if _premium_role:
                    _agent_timeout = 900.0 if _is_complex_render else 600.0
                else:
                    _agent_timeout = 480.0 if _is_complex_render else 300.0
            elif channel == "agent_api":
                # Admin/dev path: WP UX kisitlamasi gecerli degil, expand_etut
                # gibi uzun tool'lara izin ver.
                if _premium_role:
                    _agent_timeout = 480.0 if (_is_complex_render or _is_etut_expand) else 300.0
                else:
                    _agent_timeout = 240.0 if (_is_complex_render or _is_etut_expand) else 150.0
            else:
                # WhatsApp UX: kisa tutmak gerek, expand_etut 150s'e cek
                if _premium_role:
                    _agent_timeout = 240.0 if (_is_etut_expand or _is_complex_render) else 150.0
                else:
                    _agent_timeout = 150.0 if _is_etut_expand else (
                        120.0 if _is_complex_render else 90.0
                    )

            # 25.46.2 (Neo 15 May): WhatsApp progressive text send callback
            # Tool dongusunde tool_use ile gelen text bloklarini ANINDA WP'ye at.
            # Feature flag: WA_PROGRESSIVE_TEXT=true (default false) — guvenli rollout.
            _wa_prog_send = None
            if channel == "whatsapp" and os.getenv("WA_PROGRESSIVE_TEXT", "false").lower() == "true":
                _wa_prog_sent_ref = {"any": False}
                async def _wa_prog_callback(intermediate_text):
                    """Ara text bloklarini WP'ye yolla — filler iptal et."""
                    try:
                        # Filler/progress watchdog'unu iptal et — ara text geldi
                        try:
                            cancel_token.set()
                        except Exception:
                            pass
                        # Mesaji yolla (best-effort, hata kullaniciyi bozmaz)
                        await send_wa_message(phone, intermediate_text)
                        _wa_prog_sent_ref["any"] = True
                    except Exception as _wpc_e:
                        logger.debug(f"  [WA-PROG-CB] hata: {_wpc_e}")
                _wa_prog_send = _wa_prog_callback

            response = await asyncio.wait_for(
                agent.run(text, caller_phone=phone, channel=channel,
                          _stream_queue=_stream_queue, _wa_progressive_send=_wa_prog_send),
                timeout=_agent_timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Agent TIMEOUT [{phone}] ch={channel}: {_agent_timeout}s asildi, mesaj: {text[:80]}")
            # Oturum 23 (Neo bağlam analizi): Kısmi cevabı yakala.
            # Streaming queue'da biriken text varsa kullanıcı o ana kadar
            # gördüğü cevabı koruyor + biz DB'ye kaydedeceğiz → "devam et"
            # dediğinde bot kendi yarım metnini görür, oradan devam eder.
            _partial = ""
            try:
                if _stream_queue is not None and hasattr(_stream_queue, "_queue"):
                    _partial = "".join(
                        str(x) for x in list(_stream_queue._queue) if isinstance(x, str)
                    )
            except Exception:
                _partial = ""
            # Kısmi cevap varsa onu göster + devam talebi
            if _partial and len(_partial) > 100:
                response = (
                    _partial.rstrip() + "\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "_⏱ Bu nokta da zaman sınırı doldu — raporun tamamı hazır değil._\n"
                    "_'devam et' yazarsan kaldığım yerden tamamlarım._"
                )
            else:
                response = (
                    "⏱ Analiz biraz uzun sürdü ve zaman sınırına takıldı. "
                    "Daha küçük parçalar halinde sorarsan sana tam cevap verebilirim:\n\n"
                    "• \"Önce sadece TYT fizik kısmı\" gibi bölerek sorabilirsin\n"
                    "• Ya da \"devam et\" yazarsan nereden bıraktıysam oradan toparlamayı denerim"
                )

            # Oturum 23 (Neo bağlam kaybı fix): TIMEOUT olduğunda bile kısmi
            # cevabı DB'ye yaz. Böylece "devam et" sonraki mesajda bot kendi
            # yarım metnini history'den görür, kaldığı yerden devam eder.
            try:
                from fermat_core_agent import _log_conversation
                # 25.36-fix: 'role' bu scope'ta tanimsiz olabilir → profile.get fallback
                _role_safe = "unknown"
                try:
                    _role_safe = profile.get("role", "unknown") if profile else "unknown"
                except Exception:
                    pass
                await _log_conversation(
                    agent.session_id, phone, _role_safe,
                    "assistant", response, ["timeout_partial"]
                )
            except Exception as _log_e:
                logger.debug(f"  timeout partial log hatasi: {_log_e}")
        finally:
            # Watchdog ve progress'i iptal et
            cancel_token.set()
            try:
                if not watchdog_task.done():
                    watchdog_task.cancel()
            except Exception:
                pass
        _agent_ms = int((_time.time() - _agent_start) * 1000)

        # Filler atildiysa, post-followup ekle (cesit + teyit)
        if filler_sent and long_intent and response and len(response) > 200:
            kategori = long_intent.get('kategori', 'analiz')
            try:
                followup = get_post_followup(kategori,
                                              profile.get('full_name', '') if profile else '')
                if followup and followup not in response:
                    response = response + followup
            except Exception:
                pass

        # Routing stats — agent kaynak tespiti (ollama/claude)
        # Oturum Mentenans (21 Nisan 19:20) — TEST MODE'da yazilmaz
        _src_for_admin = "claude"  # default — admin footer için
        try:
            # Oturum 18: pool kullan, 2 conn yerine 1 acquire (~100ms tasarruf)
            _pool3 = await get_db_pool()
            async with _pool3.acquire() as _conn3:
                _last = await _conn3.fetchval(
                    "SELECT tools_used::text FROM agent_conversations WHERE phone=$1 AND message_role='assistant' ORDER BY created_at DESC LIMIT 1",
                    phone)
                # 25.22 Cerebras destekli source detection
                # Granüler: cerebras_8b / cerebras_120b (235b qwen 25.49 emekli, branch geçmiş veri için)
                _last_str = str(_last or "")
                _ll = _last_str.lower()
                if "cerebras_235b" in _ll:
                    _src = "cerebras_235b"
                elif "cerebras_120b" in _ll:
                    _src = "cerebras_120b"
                elif "cerebras_8b" in _ll:
                    _src = "cerebras_8b"
                elif "cerebras" in _ll:
                    _src = "cerebras"
                elif "groq_local" in _ll or "groq" in _ll:
                    _src = "groq"
                elif "ollama" in _ll:
                    _src = "ollama"
                else:
                    _src = "claude"
                _src_for_admin = _src
                # 22.1n-neo: Claude icin handler_name = son tool_call adi (tools_used'dan parse)
                _claude_tool = None
                try:
                    if _last:
                        import json as _json
                        _tlist = _json.loads(_last) if _last.startswith('[') else None
                        if _tlist and isinstance(_tlist, list) and _tlist:
                            _claude_tool = str(_tlist[0])[:50]
                except Exception:
                    pass
                # Decision trace okuma — Oturum 25.29 observability
                # Agent'in bu turun trace'ini last_* alanlarinda biriktiriyor.
                # Bug debug: "neden bu yola gitti?" → routing_stats.decision_trace JSONB
                try:
                    import json as _json_trace
                    _trace = getattr(agent, "last_decision_trace", None) or {}
                    _tools = list(getattr(agent, "last_tools_called", None) or [])
                    _blocks = list(getattr(agent, "last_prompt_blocks", None) or [])
                    # 25.40z3-ROUTING-FIX2: Decision trace 'unknown' bug fix
                    # Bridge level garanti: route hala "unknown" ise _src'den türet
                    # Fast path agent.run() çağırmadığı için trace boş → unknown kalıyordu
                    if not _trace or _trace.get("route") == "unknown":
                        if not _trace:
                            _trace = {}
                        # _src bridge'den geliyor: "fast_response", "claude", "cerebras_235b" vb.
                        if _src == "fast_response":
                            _trace["route"] = "fast"
                        elif _src and _src.startswith("cerebras"):
                            _trace["route"] = f"local_{_src}"
                        elif _src in ("groq", "ollama"):
                            _trace["route"] = f"local_{_src}"
                        elif _src == "claude":
                            _trace["route"] = "claude"  # tool_loop/text_only agent set etmediyse
                        elif _src:
                            _trace["route"] = _src
                    # Source bilgisini de trace'e yaz (granuler analiz icin)
                    if not _trace.get("source"):
                        _trace["source"] = _src
                    _trace_json = _json_trace.dumps(_trace, ensure_ascii=False) if _trace else None
                except Exception:
                    _trace_json = None
                    _tools = None
                    _blocks = None
                if not _is_test_mode():
                    # 25.42 (Bulgu F): test_user flag
                    try:
                        from test_user_registry import is_test_phone as _is_test_p
                        _is_test_main = _is_test_p(phone)
                    except Exception:
                        _is_test_main = False
                    await _conn3.execute(
                        "INSERT INTO routing_stats (phone, role, message, response_source, response_ms, handler_name, decision_trace, tools_called, prompt_blocks, is_test_user) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10)",
                        phone, profile.get("role",""), text[:200], _src, _agent_ms, _claude_tool,
                        _trace_json, _tools or None, _blocks or None, _is_test_main)
        except Exception as _rstats_err:
            logger.warning(f"routing_stats yazim hatasi: {_rstats_err}")

        # ═══════════════════════════════════════════════════════════════════
        # CLASSROOM MANAGEMENT — Token kullanımı kaydet (budget tracking)
        # ═══════════════════════════════════════════════════════════════════
        try:
            if not _is_test_mode() and profile and response:
                from token_budget import record_interaction as _cm_rec
                await _cm_rec(
                    phone=phone,
                    role=profile.get("role", ""),
                    user_msg=text or "",
                    bot_response=response or "",
                    source=_src_for_admin,  # 'ollama' | 'claude'
                )
        except Exception as _cm_rec_e:
            logger.debug(f"  classroom usage record hata: {_cm_rec_e}")

        # ── Admin self-awareness footer — Neo route'unu/modelini/süresini bilsin ──
        if phone == "905051256802" and response:
            if _src_for_admin == "ollama":
                _model_label = "*ollama* · qwen2.5:7b"
            else:
                _model_label = "*claude* · opus-4.6"
            response = response + f"\n\n_⚙ via {_model_label} · {_agent_ms/1000:.1f}s_"

        # Ogrenci etkilesim loglama — pedagojik veri toplama
        try:
            from fermat_core_agent import _get_caller_profile
            prof = await _get_caller_profile(phone)
            if prof.get("role") == "ogrenci":
                await _log_student_interaction(phone, prof, text, intent if 'intent' in dir() else None)

                # Duygu analizi — otomatik sentiment tracking
                try:
                    from sentiment_tracker import detect_sentiment, log_sentiment
                    sentiment = detect_sentiment(text)
                    if sentiment != "neutral":
                        soz_no = prof.get("soz_no") or 0
                        await log_sentiment(phone, int(soz_no), prof.get("full_name",""), text, sentiment)
                        logger.info(f"  [DUYGU] {prof.get('full_name','')}: {sentiment}")
                except Exception as _se:
                    logger.debug(f"  Sentiment hatasi: {_se}")

                # 22.1n-fikir1: Dogal insight extraction (fire-and-forget, arka plan)
                # Neo DIREKT talimat 20 Nisan 14:00 — konusmadan organik cikarim, time-decay
                # MESAJ GONDERMEZ (outreach guard zaten kapali) — sadece DB yazar
                try:
                    from insight_extractor import run_extraction_background
                    _soz_no_ex = prof.get("soz_no")
                    # OTURUM 22.6 (21 Nisan) — _safe_background_task ile sarmalandi
                    _safe_background_task(run_extraction_background(
                        phone=phone,
                        soz_no=int(_soz_no_ex) if _soz_no_ex else None,
                        user_msg=text or "",
                        bot_msg=(response or "")[:400],
                    ), label="insight_extract")
                except Exception as _ie:
                    logger.debug(f"  insight extract hata: {_ie}")
        except Exception:
            pass

        return response or "Yanit uretilemedi."
    except Exception as e:
        err_str = str(e)
        # OTURUM 23.2 (21 Nisan) — exc_info=True, traceback log'a yazilir.
        # Bugünkü UnboundLocalError sessizce yutulduguiçin 4 saat kimse fark etmemisti.
        # Artik logda tam stacktrace var — debug hizlanir.
        #
        # 25.44 BUG FIX (bot dev meeting #5, 12 May 19:31): Loguru curly-brace KeyError
        # Sentry/journal'da gozuktu — Claude SDK exception'inda err_str icinde
        # `{'type': 'text', ...}` dict repr olunca loguru `{type}` format key
        # sanip KeyError: 'type' atti. HTTP 500 — orijinal hata maskelenmisti.
        # Cozum: loguru positional binding (opt(raw=True) yerine — opt API
        # eski surumlerde stable degil). Brace'leri escape et.
        safe_err = err_str.replace("{", "{{").replace("}", "}}")
        safe_phone = str(phone).replace("{", "{{").replace("}", "}}")
        logger.error(f"Agent hatasi [{safe_phone}]: {safe_err}", exc_info=True)

        # Anthropic API 500 / 529 (overloaded) — bu teknik sorun, kullanici suclu degil
        # Bir kere retry dene (genelde gecici)
        is_api_transient = any(code in err_str for code in ['500', '529', 'Internal server error', 'overloaded'])
        # 25.44-dev-meeting-9 (Neo bug 14 May 22:32): 400 history corruption
        # 'tool_use ids were found without tool_result' — dev-meeting-4'te fix
        # vardi ama yeterli olmadi (native stream + tool fragmentleri yakalanmadi).
        # Retry'i tetikle + history'i SADECE TEXT'e sanitize et (tool block'lari at).
        is_history_corrupted = (
            '400' in err_str
            and 'tool_use' in err_str.lower()
            and 'tool_result' in err_str.lower()
        )
        if is_history_corrupted:
            try:
                _cleaned = 0
                for _msg in (agent.history or []):
                    _content = _msg.get("content")
                    if not isinstance(_content, list):
                        continue
                    _filtered = []
                    for _b in _content:
                        if isinstance(_b, dict) and _b.get("type") in ("tool_use", "tool_result"):
                            _cleaned += 1
                            continue
                        _filtered.append(_b)
                    if not _filtered:
                        # Tüm content tool block idi — minimal placeholder
                        _msg["content"] = "[önceki tool sonucu — temizlendi]"
                    elif all(isinstance(b, dict) and b.get("type") == "text" for b in _filtered):
                        # Sadece text kaldı — string'e çevir (Claude için temiz format)
                        _msg["content"] = "\n".join(b.get("text", "") for b in _filtered)
                    else:
                        _msg["content"] = _filtered
                logger.warning(
                    f"  [HISTORY-CORRUPT-CLEANUP] {_cleaned} tool block silindi, retry oncesi text-only"
                )
            except Exception as _ch:
                logger.error(f"  [HISTORY-CLEANUP] fail: {_ch}")

        if is_api_transient or is_history_corrupted:
            _retry_label = "[API-RETRY]" if is_api_transient else "[HISTORY-RETRY]"
            logger.warning(f"  {_retry_label} 2sn sonra tekrar deniyoruz [{phone}]")
            await asyncio.sleep(2)
            try:
                response = await asyncio.wait_for(
                    agent.run(text, caller_phone=phone, channel=channel, _stream_queue=_stream_queue),
                    timeout=60.0
                )
                if response:
                    logger.success(f"  {_retry_label} Basarili [{phone}]")
                    return response
            except Exception as retry_err:
                logger.error(f"  {_retry_label} Ikinci deneme de basarisiz [{phone}]: {retry_err}")

        # Hata mesaji — kullanici odakli, suclu hissettirmeyen
        if is_api_transient:
            err_msg = (
                "Su an teknik bir aksaklik yasiyoruz 🔧\n\n"
                "Anthropic API tarafinda gecici bir yuk var. "
                "Birkac saniye sonra ayni soruyu tekrar yazarsan yanitlarim 🙏"
            )
        else:
            err_msg = (
                "Mesajini islerken bir sorun olustu. 😕\n\n"
                "Biraz daha kisa veya net bir sekilde tekrar yazar misin?"
            )
        # DB'ye de kaydet (eksik log sorunu cozuldu)
        try:
            from fermat_core_agent import _log_conversation, _get_caller_profile as _gcp_err
            sid = getattr(agent, 'session_id', '') or ''
            prof = {"role": "unknown"}
            try:
                prof = await _gcp_err(phone)
            except Exception as _pe:
                logger.debug(f"  err fallback profile hatasi: {_pe}")
            await _log_conversation(sid, phone, prof.get("role","unknown"), "assistant", err_msg, ["error_fallback"])
        except Exception as _le:
            logger.debug(f"  err fallback log hatasi: {_le}")
        return err_msg


async def _log_student_interaction(phone: str, profile: dict, text: str, intent=None) -> None:
    """Ogrenci etkilesimini DB'ye kaydet — pedagojik veri toplama."""
    if not DATABASE_URL:
        return
    try:
        # Konu tespiti (basit keyword analizi)
        text_lower = text.lower()
        konu = "genel"
        for subject, keywords in [
            ("matematik", ["mat", "matematik", "denklem", "fonksiyon", "geometri"]),
            ("fizik", ["fiz", "fizik", "kuvvet", "enerji", "hareket"]),
            ("kimya", ["kim", "kimya", "element", "mol", "reaksiyon"]),
            ("biyoloji", ["biyo", "biyoloji", "hucre", "gen", "dna"]),
            ("turkce", ["turkce", "turk", "dil", "edebiyat", "paragraf"]),
            ("ingilizce", ["ing", "english", "ingilizce", "grammar"]),
            ("tarih", ["tarih", "osmanli", "cumhuriyet"]),
        ]:
            if any(kw in text_lower for kw in keywords):
                konu = subject
                break

        # Oturum 18: pool kullan — her ogrenci mesajinda 50-100ms tasarruf
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agent_conversations
                   (session_id, phone, role, message_role, content, tools_used)
                   VALUES ($1, $2, 'ogrenci', 'student_interaction', $3, $4)""",
                f"interaction_{phone[-4:]}",
                phone,
                text[:2000],
                [konu],
            )

        # In-memory istatistik guncelle
        if phone not in _STUDENT_INTERACTION_STATS:
            _STUDENT_INTERACTION_STATS[phone] = {}
        stats = _STUDENT_INTERACTION_STATS[phone]
        stats[konu] = stats.get(konu, 0) + 1

        logger.info(f"  Ogrenci etkilesim: {profile.get('full_name','')} konu={konu}")
    except Exception as e:
        logger.warning(f"Ogrenci etkilesim log hatasi: {e}")


# ── FastAPI Endpoint'leri ─────────────────────────────────────────────────────

@app.get("/webhook")
async def webhook_verify(request: Request):
    """
    Meta webhook doğrulama (GET).
    Meta 'hub.challenge' değerini döndürülmesini bekler.
    """
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WA_VERIFY_TOKEN:
        logger.success("✅ Webhook doğrulandı")
        return PlainTextResponse(challenge)

    logger.warning(f"⚠️  Webhook doğrulama başarısız — token: {token}")
    raise HTTPException(status_code=403, detail="Doğrulama başarısız")


@app.post("/webhook")
async def webhook_receive(request: Request):
    """
    Meta webhook mesaj alıcısı (POST).
    Metin, ses ve görüntü mesajlarını işler.
    """
    # OTURUM 23.3 (21 Nisan) — Webhook sure olcumu ve timeout alarmi
    # Meta'nin timeout'u ~20sn. 18sn uzeri WARN, 20sn uzeri ERROR (Meta retry yapar, dup mesaj).
    import time as _wh_time
    _wh_start = _wh_time.time()

    body = await request.body()

    # İmza doğrulama — client IP ile (secret yoksa localhost-only fallback)
    sig = request.headers.get("X-Hub-Signature-256", "")
    client_ip = request.client.host if request.client else ""
    if not verify_signature(body, sig, client_ip=client_ip):
        logger.warning(f"⚠️  Geçersiz webhook imzası (IP: {client_ip})")
        raise HTTPException(status_code=403, detail="İmza geçersiz")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=200)

    # 25.44-dev-meeting-10 (Neo bug 14 May, Sentry #116905082):
    # Eski kod `await _handle_webhook_data(data)` ile mesaj islemeyi SENKRON
    # bekliyordu. process_message (LLM + tool) 25s surunce Meta'nin 20s
    # webhook timeout'u asiliyor → Meta dup mesaj / retry gonderiyor.
    # FIX: isi background task'a at, Meta'ya ANINDA 200 don. _safe_background_task
    # exception'i log'lar, fire-and-forget guvenli.
    try:
        _safe_background_task(_handle_webhook_data(data), label="webhook")
    except Exception as e:
        logger.error(f"Webhook task baslatma hatasi: {e}", exc_info=True)

    # OTURUM 23.3 → 25.44: Sure olcumu artik SADECE sync kismi (imza+parse+task
    # baslatma) olcer — bu <100ms olmali. 1s ustu anormal, loglanir.
    _wh_dur = _wh_time.time() - _wh_start
    if _wh_dur > 1.0:
        logger.warning(
            f"⚠ Webhook sync kismi yavas: {_wh_dur:.2f}s "
            f"(imza/parse/task-baslatma — normalde <100ms)"
        )

    return Response(status_code=200)


async def _handle_webhook_data(data: dict) -> None:
    """Webhook payload'ını parse et ve mesajı işle."""
    # Meta webhook yapısı
    entry = data.get("entry", [])
    for e in entry:
        for change in e.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                await _handle_single_message(msg, value)


async def _handle_single_message(msg: dict, value: dict) -> None:
    """Tek bir WhatsApp mesajını işle."""
    msg_id  = msg.get("id", "")
    # Telefon numarasini normalize et — tum downstream INSERT'ler 905xxx formatinda
    from phone_utils import normalize_phone as _norm
    raw_phone = msg.get("from", "")
    phone   = _norm(raw_phone) or raw_phone  # fallback: ham deger (normalize edemezse)
    msg_type = msg.get("type", "")

    # Çift işlem önleme
    # Oturum Mentenans (21 Nisan 18:30) — Redis'e taşındı + in-memory fallback.
    # Bridge restart sonrasi Meta retry gelse bile dup islenmiyor (Redis persist).
    # TTL=1 saat (Meta 24 saate kadar retry yapabilir ama 1 saat yeterli — yeni
    # mesaj ayni ID'yi kullanmaz).
    if msg_id:
        _is_dup = False
        try:
            from session_store import get_store
            _store = get_store()
            # Redis set with NX (set if not exists) — atomik
            if hasattr(_store, '_get_client'):
                _rc = await _store._get_client()
                # SET key value NX EX=3600 → 1 saat TTL
                _redis_key = f"wa:msg:processed:{msg_id}"
                _ok = await _rc.set(_redis_key, "1", ex=3600, nx=True)
                _is_dup = not _ok  # NX başarısızsa zaten varmış
        except Exception as _dup_e:
            logger.debug(f"  Redis dup check fail (memory fallback): {_dup_e}")
            # Fallback: in-memory set
            _is_dup = msg_id in _PROCESSED_MSG_IDS

        if _is_dup:
            logger.info(f"  [DUP-SKIP] Tekrar gelen mesaj (msg_id={msg_id[-16:]})")
            return

    # In-memory fallback — Redis down olursa da koruma olsun
    _PROCESSED_MSG_IDS.add(msg_id)
    if len(_PROCESSED_MSG_IDS) > 5000:  # Bellek yönetimi — eski ID'leri at, tamamen silme
        # En eski yarısını at (set sırasız ama yine de azalt)
        to_remove = list(_PROCESSED_MSG_IDS)[:2500]
        for mid in to_remove:
            _PROCESSED_MSG_IDS.discard(mid)

    # Eski mesaj kontrolu — 5 dakikadan eski mesajlari atla (restart sonrasi birikmis mesajlar)
    msg_timestamp = msg.get("timestamp")
    if msg_timestamp:
        try:
            import time
            msg_age = time.time() - int(msg_timestamp)
            if msg_age > 300:  # 5 dakikadan eski
                logger.warning(f"  Eski mesaj atlandi ({int(msg_age)}sn once): {msg_id}")
                return
        except (ValueError, TypeError):
            pass

    logger.info(f"📨 [{phone}] Tip: {msg_type} | ID: {msg_id}")

    text = ""
    audio_bytes = None

    if msg_type == "text":
        text = msg.get("text", {}).get("body", "")

    elif msg_type == "audio":
        # 22.1l — Whisper entegrasyon: ses → metin
        media_id = msg.get("audio", {}).get("id", "")
        if media_id:
            audio_bytes = await download_wa_media(media_id)
            if not audio_bytes:
                await send_wa_message(phone, "⚠️ Ses mesajı indirilemedi.")
                return
            text = await _transcribe_audio(audio_bytes) or "[SES MESAJI — anlasilamadi]"
        else:
            text = "[SES MESAJI]"

    elif msg_type == "voice":
        media_id = msg.get("voice", {}).get("id", "")
        if media_id:
            audio_bytes = await download_wa_media(media_id)
            text = await _transcribe_audio(audio_bytes) or "[SES NOTU — anlasilamadi]"
        else:
            text = "[SES NOTU]"

    elif msg_type == "image":
        # Kayitsiz numara foto gonderemez — token/islemci korumasi
        profile_check = await _is_phone_registered(phone)
        if not profile_check:
            await send_wa_message(phone,
                "Fotograf analizi sadece kayitli ogrencilerimize sunulan bir hizmettir.\n\n"
                "Kurumumuz hakkinda bilgi almak icin yazili mesaj gonderebilirsiniz.\n"
                "Randevu: fermategitimkurumlari.com/randevu\n"
                "Tel: +90 546 260 54 46")
            return

        caption = msg.get("image", {}).get("caption", "")
        image_id = msg.get("image", {}).get("id", "")

        # 22.1n-neo FINANS GUARD — Caption finans iceriyorsa Vision KAPALI
        # Neo bile screenshot atarsa Anthropic sunucuya base64 gitmesin
        try:
            from finans_access import is_finans_content, log_finans_access
            if is_finans_content(caption):
                await log_finans_access(
                    phone, "vision_blocked",
                    target="photo_solve",
                    details=f"finans_keyword in caption: {caption[:80]}",
                    success=False
                )
                await send_wa_message(phone,
                    "📸 Fotografta finansal icerik tespit edildi.\n\n"
                    "Guvenlik nedeniyle finansal ekran goruntuleri Vision ile analiz edilmez. "
                    "Finansal verileri lutfen manuel giris ekraninda veya DB'ye dogrudan gir."
                )
                return
        except Exception:
            pass

        # Foto limiti kontrolu — v2 dinamik (aktif ogrenciye +2)
        today_str = datetime.now().strftime("%Y-%m-%d")
        phone_normalized = _normalize_phone(phone)

        # soz_no bul (ACL'den)
        student_soz_no = None
        try:
            from fermat_core_agent import _get_caller_profile
            profile = await _get_caller_profile(phone)
            student_soz_no = profile.get('soz_no') if profile else None
        except Exception:
            pass

        # Dinamik limit (aktif ogrenciye 5, digerlere 3)
        # Oturum 25.40 (Neo direktif): Admin (Neo) için foto limit BYPASS
        NEO_PHONE = "905051256802"
        if phone_normalized == NEO_PHONE:
            # Neo sınırsız foto — dev/test
            daily_limit = 9999
            pc = _PHOTO_COUNTS.get(phone_normalized, {"date": today_str, "count": 0})
            if pc["date"] != today_str:
                pc = {"date": today_str, "count": 0}
            pc["count"] += 1
            _PHOTO_COUNTS[phone_normalized] = pc
            kalan = 9999
        else:
            try:
                from foto_solver_v2 import get_dynamic_photo_limit
                daily_limit = await get_dynamic_photo_limit(student_soz_no, _PHOTO_DAILY_LIMIT)
            except Exception:
                daily_limit = _PHOTO_DAILY_LIMIT

            pc = _PHOTO_COUNTS.get(phone_normalized, {"date": "", "count": 0})
            if pc["date"] != today_str:
                pc = {"date": today_str, "count": 0}
            if pc["count"] >= daily_limit:
                await send_wa_message(phone,
                    f"📸 Gunluk foto soru cozum limitine ulastin ({daily_limit}/{daily_limit}).\n\n"
                    f"Yarin yeniden kullanabilirsin!\n"
                    f"_Simdilik soruyu yazi olarak da sorabilirsin — yardimci olurum._ 🎯")
                return
            pc["count"] += 1
            _PHOTO_COUNTS[phone_normalized] = pc
            kalan = daily_limit - pc["count"]

        # Fotoyu indir ve Vision API ile coz
        if image_id:
            image_bytes = await download_wa_media(image_id)
            if not image_bytes:
                # Download başarısız — retry 1 kez
                logger.warning(f"Foto download başarısız, retry... [{phone}]")
                import asyncio as _aio_retry
                await _aio_retry.sleep(2)
                image_bytes = await download_wa_media(image_id)
            if not image_bytes:
                # 2. deneme de başarısız — öğrenciye bildir
                await send_wa_message(phone,
                    "📸 Fotoğrafını alamadım — teknik bir sorun oldu.\n\n"
                    "Lütfen *tekrar gönder* veya soruyu *yazarak* sor.\n\n"
                    "_Eğer sorun devam ederse birkaç dakika sonra tekrar dene._ 🔄")
                return
            if image_bytes:
                # Cesitlilikli pre-filler (varyasyonlar arasi rotasyon)
                try:
                    from conversation_flow import pick_filler
                    foto_filler = pick_filler('foto_solve', phone)
                    foto_filler += f"\n\n_Bugun kalan foto hakkin: *{kalan}*_"
                    await send_wa_message(phone, foto_filler)
                except Exception:
                    await send_wa_message(phone,
                        f"📸 Soruyu inceliyorum... 🔍\n"
                        f"_Bugun kalan foto hakkin: *{kalan}*_")
                try:
                    # v2: zayif konu eslestirme + cikmis soru onerisi + topic tracker guncelleme
                    try:
                        from foto_solver_v2 import solve_photo_v2
                        solution = await solve_photo_v2(
                            image_bytes,
                            caption or "Bu soruyu cozer misin?",
                            soz_no=student_soz_no,
                            phone=phone,
                            role="ogrenci",
                        )
                    except Exception as v2_err:
                        logger.warning(f"v2 fallback to v1: {v2_err}")
                        solution = await _solve_photo_question(image_bytes, caption or "Bu soruyu cozer misin?")
                    # Foto cozumunu DIREKT gonder — process_message'a gonderme
                    # (process_message fast_response pattern'larina takilir)
                    if solution:
                        await send_wa_message(phone, solution)
                        # DB'ye kaydet
                        try:
                            _sid = getattr(_AGENT_SESSIONS.get(phone), 'session_id', 'foto')
                            await db_execute(
                                "INSERT INTO agent_conversations (session_id, phone, role, message_role, content, tools_used) VALUES ($1,$2,$3,$4,$5,$6)",
                                _sid, phone, "ogrenci", "assistant", solution[:2000], ["claude_vision"])
                        except Exception:
                            pass
                        # 22.1n-neo: Foto context kaydet (Fatma bug fix) — sonraki follow-up
                        # sorularda Claude'a context injection yapilacak (30 dk TTL)
                        try:
                            from conversation_memory import set_photo_context, _CONTEXT_CACHE
                            set_photo_context(phone, solution)
                            # Cache invalidate: bir sonraki get_student_context yenileme zorla
                            _CONTEXT_CACHE.pop(phone.replace("+",""), None)
                        except Exception:
                            pass
                    return
                except Exception as e:
                    logger.error(f"Foto cozum hatasi: {e}")
                    await send_wa_message(phone, "Fotografi isleyemedim. Soruyu yazi olarak yazar misin?")
                    return
        text = caption or "[Fotograf]"

    elif msg_type == "video":
        if not VIDEO_ENABLED:
            await send_wa_message(phone,
                "Su an video mesajlari desteklenmemektedir. "
                "Sorunuzu yazi veya fotograf olarak gonderebilirsiniz.")
            return

    elif msg_type == "document":
        await send_wa_message(phone,
            "Dokuman gonderimi su an desteklenmemektedir. "
            "Sorunuzu yazi veya fotograf olarak gonderebilirsiniz.")
        return

    elif msg_type == "sticker":
        return  # Sticker'a yanit verme

    elif msg_type == "reaction":
        # Emoji reaction (👍❤️ vb.) — bot konusmayi bolmemeli, sadece logla
        reaction_emoji = msg.get("reaction", {}).get("emoji", "")
        reacted_to_id = msg.get("reaction", {}).get("message_id", "")
        logger.info(f"  Reaction: {reaction_emoji} → msg_id={reacted_to_id}")
        # Olumlu reaction (1-5x kez kullaniciya cevap atma):
        # opsiyonel: olumlu reaction'da "_Memnun olduguna sevindim_" gibi rare ack
        # Simdilik sessiz kal — sureci bolme
        return

    elif msg_type == "interactive":
        # Buton yanıtı
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            text = interactive["button_reply"].get("title", "")
        elif interactive.get("type") == "list_reply":
            text = interactive["list_reply"].get("title", "")

    else:
        logger.info(f"  Desteklenmeyen mesaj tipi: {msg_type}")
        return

    if not text and not audio_bytes:
        return

    # Rate limit kontrolu
    if not _check_rate_limit(phone, msg_len=len(text or "")):
        logger.warning(f"  Rate limit asildi: {phone}")
        await send_wa_message(phone, "Cok fazla mesaj gonderiyorsunuz. Lutfen biraz bekleyin.")
        return

    # Gelen mesajı logla
    logger.info(f"  Mesaj: {text[:80]}")

    # ── PER-PHONE QUEUE/LOCK ───────────────────────────────────────────────────
    # Ayni phone'dan ardisik mesaj geldiginde:
    #  - Suanki agent.run cakismasin
    #  - Yeni mesaj queue'ya birikir
    #  - Lock biter bitmez biriken mesajlar TEK context olarak isleniyor
    await _enqueue_and_process(phone, text, audio_bytes)


# ─────────────────────────────────────────
# PER-PHONE MESAJ KUYRUGU
# ─────────────────────────────────────────
# 22.1n-neo Paket A: HybridPhoneLocks (memory asyncio.Lock — Redis distributed
# lock Ağustos migration'da eklenecek, su an memory worker-local).
_PHONE_LOCKS = HybridPhoneLocks()
# _PHONE_QUEUES: bytes objesi tutabiliyor (audio) → JSON serialize risk, memory only
_PHONE_QUEUES: dict[str, list] = {}  # {phone: [(text, audio_bytes, enqueued_at), ...]}
_QUEUE_NOTIFIED = HybridDict("queue_notif:", ttl_default=60)  # son notification zamani
_LOCK_ACQUIRED_AT = HybridDict("lock_at:", ttl_default=300)   # stale lock detection


def _get_phone_lock(phone: str) -> asyncio.Lock:
    return _PHONE_LOCKS.get(phone)


async def _enqueue_and_process(phone: str, text: str, audio_bytes: bytes | None):
    """
    Per-phone queue ile mesaj islemi.

    Akis:
    - Lock bos: hemen process_message + cevap, lock release sonrasi queue'yu kontrol
    - Lock dolu: queue'ya ekle + (ilk birikende) "gordum, biraz onceki sorunu da
      goz onunde bulunduracagim" tarzi kibar bilgi mesaji at

    22.1n-queuefix (Damla vakasi):
    - Duplicate mesaj check: son 10sn icinde AYNI metin gelmisse queue'ya EKLEME (sessiz dedupe)
    - Kullanici "gelmedi" hissiyle ayni mesaji tekrar yazdiginda 2 kopya degil 1 kopya isler
    """
    import time as _t
    lock = _get_phone_lock(phone)

    # 22.1n-queuefix: Stale lock detection — 180sn'den uzun suren lock'u zorla temizle
    if lock.locked():
        acquired = _LOCK_ACQUIRED_AT.get(phone, 0)
        if acquired and (_t.time() - acquired) > 180:
            logger.warning(f"  ⚠️  Stale lock tespit (phone={phone[-4:]}, {int(_t.time()-acquired)}s) — release ediliyor")
            try:
                # Lock'u zorla release et (yeni bir Lock yarat, eski orphan olsun)
                _PHONE_LOCKS[phone] = asyncio.Lock()
                lock = _PHONE_LOCKS[phone]
                _LOCK_ACQUIRED_AT.pop(phone, None)
                # 25.40r-BUGFIX: Redis distributed lock'u da temizle (orphan onleme).
                # Memory lock reset edilince Redis SETNX TTL=180sn boyunca asili kalmasin —
                # yoksa o kullanicinin sonraki mesajlari acquire_distributed FAIL ile drop olur.
                try:
                    await _PHONE_LOCKS.release_distributed(phone)
                except Exception:
                    pass
                # Kullanicini bilgilendir
                try:
                    await send_wa_message(phone, "⚠️ Önceki işlemim çok uzadı, yeniden başlatıyorum. Lütfen sorunu tekrar yaz 🙏")
                except Exception:
                    pass
            except Exception:
                pass

    # Lock dolu mu? (suanki kullanici icin agent zaten calisiyor mu?)
    if lock.locked():
        # 22.1n-queuefix: Duplicate check — ayni metin son 10sn'de queue'ya atilmissa atla
        now = _t.time()
        if phone not in _PHONE_QUEUES:
            _PHONE_QUEUES[phone] = []
        existing = _PHONE_QUEUES[phone]
        _norm_text = (text or "").strip().lower()
        # Her entry: (text, audio_bytes, enqueued_at)
        for entry in existing:
            if len(entry) >= 3:
                prev_text, _, prev_time = entry[0], entry[1], entry[2]
                if (prev_text or "").strip().lower() == _norm_text and (now - prev_time) < 10:
                    logger.info(f"  ⏭️  Duplicate atlandi (phone={phone[-4:]}, text={_norm_text[:30]!r})")
                    return
        existing.append((text, audio_bytes, now))
        logger.info(f"  📚 Queue'ya eklendi (phone={phone[-4:]}, kuyruk={len(existing)})")

        # Spam onleme: 30sn'de 1 kez bilgi mesaji
        import time as _time
        last_notif = _QUEUE_NOTIFIED.get(phone, 0)
        if _time.time() - last_notif > 30:
            _QUEUE_NOTIFIED[phone] = _time.time()
            from conversation_flow import _PRE_FILLERS
            # Oturum 22: 7 → 18 varyasyon (B6 — daha zengin, robot hissi azalsın)
            queue_msgs = [
                "📥 Gördüm, önceki sorunla işim bitince bunu da cevaplarım. Birkaç saniye ⏳",
                "💭 Şu an öncekiyle uğraşıyorum, bunu kaybetmeyeceğim — sırayla bakacağım 🙏",
                "✋ Aldım, önceki analizi bitirdikten hemen sonra bu da sırada ⏰",
                "📝 Notuna ekledim, öncekini bitirir bitirmez buna geçerim 🎯",
                "🤝 Sırada — önce ilk mesajı cevaplayayım, sonra buna dönerim ✨",
                "⏱️ İki soru arka arkaya geldi, sırayla işliyorum. Ellem bitince sıra sende 💪",
                "👀 Farkındayım — öncekine odaklanmışım, hemen arkasından buna bakarım 🌟",
                "🧠 Kafamda iki soru var şu an, önceki bitmeden ikincisine geçmeyeyim 🙂",
                "💬 Önce biriyle ilgileneyim ama seni unutmuyorum — 30sn kadar 🎯",
                "🎭 Multi-task değilim ben, tek tek samimi cevap isterim — sen de sıraya gir 💙",
                "🔄 Önceki düşünce silsilem bitsin, sonra bu soruyu tazelikle çözerim ⏳",
                "📚 Önceki soru derine indi, bu da önemli ama biraz bekletmem gerek 🙏",
                "🫷 Dur bir saniye, ilk soruyu bitireyim — sonra sen de hak ettiğin cevabı alırsın ⚡",
                "🍵 Yerine geç bir çay iç — birini bitir sonra hemen döneceğim 😄",
                "🧩 Beynim şu an önceki puzzle ile meşgul, seninkine birazdan geçerim 🎯",
                "⚙️ Aynı anda iki motor çevirmem, önceki bitince bu motoru çalıştırırım ⏰",
                "🎼 Sırayla enstrüman çalıyorum — öncekisi bitsin, sıra sende 🎵",
                "🪄 Sabırla gelen iyi cevap > aceleyle yazılan yüzeysel cevap. Biraz bekle ✨",
            ]
            import random as _r
            try:
                await send_wa_message(phone, _r.choice(queue_msgs))
            except Exception:
                pass
        return

    # Lock bos — hemen isle
    # 25.40r: Distributed lock wrapper (workers>=2 icin Redis SETNX cross-worker
    # serialize. Memory mode'da no-op, davranis aynen korunur)
    redis_acquired = await _PHONE_LOCKS.acquire_distributed(phone, timeout=30.0, ttl=180)
    if not redis_acquired:
        # Cross-worker'da baska worker bu kullanici icin islem yapiyor
        # Memory'de gorulmedigi icin queue'ya da konmadi → sessizce drop
        # (kullanici tekrar yazsin; gercek production'da nadir gerceklesir)
        logger.warning(f"  ⏳ Cross-worker lock timeout {phone[-4:]}, mesaj drop (kullanici tekrar yazabilir)")
        return
    try:
        async with lock:
            _LOCK_ACQUIRED_AT[phone] = _t.time()  # 22.1n-queuefix: stale detect icin
            try:
                await _process_one_message(phone, text, audio_bytes)
            finally:
                _LOCK_ACQUIRED_AT.pop(phone, None)
    finally:
        await _PHONE_LOCKS.release_distributed(phone)

    # Lock release sonrasi queue'da birikenler varsa, SIRAYLA TEK TEK isle
    # (eskiden merge ediyordu, Claude sadece sonuncuyu cevapliyordu — kullanici bag kaybediyor)
    while _PHONE_QUEUES.get(phone):
        # 25.40r: Her queue iterasyonu icin de distributed lock al (worker degisebilir)
        redis_acquired_q = await _PHONE_LOCKS.acquire_distributed(phone, timeout=30.0, ttl=180)
        if not redis_acquired_q:
            logger.warning(f"  ⏳ Queue cross-worker lock timeout {phone[-4:]}, kuyruk birakiliyor")
            break
        try:
            async with lock:
                _LOCK_ACQUIRED_AT[phone] = _t.time()
                try:
                    pending = _PHONE_QUEUES.get(phone, [])
                    if not pending:
                        break
                    # Kuyruktan SADECE ilkini al, digerleri kalir (sirayla islenir)
                    # 22.1n-queuefix: 3-tuple (text, audio, enqueued_at) destegi
                    entry = pending.pop(0)
                    p_text = entry[0]
                    p_audio = entry[1] if len(entry) >= 2 else None
                    if not pending:
                        _PHONE_QUEUES.pop(phone, None)
                    logger.info(f"  📬 Queue'dan isleniyor (phone={phone[-4:]}, kalan={len(pending)})")
                    await _process_one_message(phone, p_text, p_audio)
                finally:
                    _LOCK_ACQUIRED_AT.pop(phone, None)
        finally:
            await _PHONE_LOCKS.release_distributed(phone)


async def _process_one_message(phone: str, text: str, audio_bytes: bytes | None):
    """Tek bir mesaj iceriği üzerinde process_message + send_wa_message + learn."""
    # Agent'la işle
    response = await process_message(phone, text, audio_bytes)

    # Yanıt gönder — uzun cevaplar anlamlı noktadan bölünür
    if response:
        if len(response) > 3500:
            # Anlamlı bölme noktası bul — gün/bölüm geçişi, --- ayırıcı
            split_point = None
            mid = len(response) // 2
            search_start = max(mid - 800, 1000)  # en az 1000 char ilk parçada
            search_end = min(mid + 800, len(response) - 500)  # en az 500 char ikinci parçada

            # 1. Gün geçişi (çalışma planlarında en doğal bölme)
            import re as _re_split
            day_markers = list(_re_split.finditer(r'\n\n📅\s*\*[A-ZÇĞİÖŞÜ]', response[search_start:search_end]))
            if day_markers:
                split_point = search_start + day_markers[len(day_markers)//2].start()

            # 2. Bölüm ayırıcı (━━━ veya ---)
            if not split_point:
                for marker in ['\n\n━━━', '\n---\n', '\n\n---']:
                    idx = response.find(marker, search_start, search_end)
                    if idx > 0:
                        split_point = idx
                        break

            # 3. Çift newline (paragraf arası)
            if not split_point:
                idx = response.rfind('\n\n', search_start, search_end)
                split_point = idx if idx > 0 else mid

            part1 = response[:split_point].rstrip()
            part2 = response[split_point:].lstrip().lstrip('-').lstrip('━').lstrip()

            # Doğal uyarı mesajı — kurumsal + samimi
            bridge_msg = "\n\n📩 _Planının devamı hemen geliyor, bekle..._"
            await send_wa_message(phone, part1 + bridge_msg)

            import asyncio as _aio
            await _aio.sleep(1.5)

            await send_wa_message(phone, part2)

            # İkinci parçayı ayri SPLIT dict'e kaydet — _PENDING_FOLLOWUP string bekliyor,
            # dict koyarsak pop sonrasi f-string birlestirme dict'i text'e cevirir (bug 13:58)
            _PENDING_SPLIT[phone] = {
                "type": "split_continuation",
                "full_response": response,
                "sent": True,
                "ts": datetime.now().isoformat(),
            }
        else:
            await send_wa_message(phone, response)

    # ── Gerçek zamanlı öğrenme + otonom güncelleme ─────────────────────────
    # OTURUM 22.6 (21 Nisan) — _safe_background_task ile sarmalandi
    try:
        _safe_background_task(_realtime_learn(phone, text, response or ""), label="realtime_learn")
        # Otonom ogrenme motoru — belli aralıklarla kendini gunceller
        from auto_learner import maybe_learn
        _safe_background_task(maybe_learn(), label="auto_learn")
    except Exception as _bg_setup_e:
        logger.warning(f"  BG task kurulum hatasi: {_bg_setup_e}")


async def _realtime_learn(phone: str, question: str, answer: str):
    """Her mesajdan sonra arka planda öğrenme analizi yap."""
    try:
        # 1. Hatalı yanıt tespiti
        is_error = any(x in (answer or "").lower() for x in [
            "bulunamadi", "bulunamadı", "hata", "tooluseblock", "textblock",
            "yapay zeka asistanıyım"
        ])

        # 2. Çok kısa yanıt
        is_short = len(answer or "") < 30

        # 3. Pattern kaydet (her 50 mesajda bir toplu analiz)
        msg_count = await db_fetchval(
            "SELECT COUNT(*) FROM agent_conversations WHERE created_at::date = CURRENT_DATE")

        if msg_count and msg_count % 50 == 0:
            # Toplu analiz tetikle
            logger.info(f"  [OGRENME] {msg_count} mesaj birikti, analiz tetikleniyor...")
            try:
                from conversation_learner import generate_learning_report
                await generate_learning_report()
            except Exception:
                pass

        if is_error or is_short:
            logger.warning(f"  [OGRENME] Sorunlu yanit: Q='{question[:50]}' A='{answer[:50]}'")
    except Exception:
        pass  # Öğrenme hatası ana akışı etkilemesin


# ── n8n HTTP Request Endpoint'i (alternatif) ─────────────────────────────────

@app.post("/agent")
async def agent_direct(request: Request):
    """
    n8n veya diğer araçlardan doğrudan agent çağrısı.
    Body: {"phone": "+905xxx", "message": "Ahmet'i raporla", "role": "admin"}
    Guvenlik: AGENT_API_KEY tanimliysa Bearer token zorunlu.
    """
    # ── API Key kontrolu ─────────────────────────────────────────────────
    if AGENT_API_KEY:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != AGENT_API_KEY:
            raise HTTPException(status_code=401, detail="Gecersiz veya eksik API key")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON")

    phone   = body.get("phone", "cli")
    message = body.get("message", "")
    # 25.37 KRITIK FIX (Neo bug): /agent endpoint cagrilarinda channel
    # parametresi process_message'a iletilmiyordu -> default 'whatsapp' kaliyordu ->
    # _use_wa_filler=True -> 3sn watchdog WP'ya filler atiyordu (KALICI #3 ihlal!).
    # Now: channel parametresini body'den al, default 'agent_api' (WP DEGIL).
    channel = body.get("channel", "agent_api")
    if channel == "whatsapp":
        # /agent endpoint'ten gelen mesajlari WP gibi davranma — agent_api olarak isaretle
        # (filler/auto-message guvenlik kalkani)
        channel = "agent_api"
    if not message:
        raise HTTPException(status_code=400, detail="message zorunlu")

    # Rate limit kontrolu — normalize phone (format bypass engelli), 'message' kullanilir 'text' degil
    from phone_utils import normalize_phone as _norm
    phone_norm = _norm(phone) or phone
    if not _check_rate_limit(phone_norm, msg_len=len(message or "")):
        raise HTTPException(status_code=429, detail="Cok fazla istek — dakikada max 10 mesaj")

    response = await process_message(phone, message, channel=channel)
    return {"success": True, "response": response, "phone": phone}


@app.get("/health")
async def health(request: Request):
    """Servis sağlık kontrolü.

    22.1n-neo pentest hardening: default minimal ("ok" sadece).
    Detayli bilgi API KEY gerektirir (recon attack korumasi).
    """
    # API key ile authenticated ise detay don
    auth = request.headers.get("Authorization", "")
    if AGENT_API_KEY and auth.startswith("Bearer ") and auth[7:] == AGENT_API_KEY:
        session_file = Path(os.getenv("SESSION_FILE", ".eyotek_session.json"))
        return {
            "status":           "ok",
            "active_sessions":  len(_AGENT_SESSIONS),
            "pending_followups": len(_PENDING_FOLLOWUP),
            "pending_splits":   len(_PENDING_SPLIT),
            "db_configured":    bool(DATABASE_URL),
            "wa_configured":    bool(WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID),
            "anthropic_configured": bool(ANTHROPIC_KEY),
            "whisper_configured": bool(OPENAI_KEY),
            "eyotek_session":   session_file.exists(),
        }
    # Public minimal
    return {"status": "ok"}


@app.delete("/session/{phone}")
async def reset_session(phone: str, request: Request):
    """Belirli bir telefon numarasının agent geçmişini sıfırla. API KEY zorunlu."""
    # Oturum 18 guvenlik: API key kontrolu (oncesinde korumasizdi)
    if AGENT_API_KEY:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != AGENT_API_KEY:
            raise HTTPException(status_code=401, detail="Bearer token gerekli")
    else:
        # AGENT_API_KEY tanimsiz ise sadece localhost'tan erisim izin
        client_ip = request.client.host if request.client else ""
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(status_code=401, detail="API key tanimsiz, sadece localhost erisimi")
    if phone in _AGENT_SESSIONS:
        _AGENT_SESSIONS[phone].reset()
        return {"success": True, "message": f"{phone} session sıfırlandı"}
    return {"success": False, "message": "Session bulunamadı"}


# ═══════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD — Neo Command Center (Oturum 18)
# Localhost-only + AGENT_API_KEY token ile korumali
# ═══════════════════════════════════════════════════════════════════════

def _dashboard_auth_check(request: Request) -> None:
    """Dashboard erisimi: localhost + (AGENT_API_KEY ile token) zorunlu."""
    client_ip = request.client.host if request.client else ""
    # Localhost zorunlu
    if client_ip not in ("127.0.0.1", "::1", "localhost", ""):
        raise HTTPException(status_code=403, detail="Sadece localhost erisimi")
    # AGENT_API_KEY varsa token kontrolu (query param 'token' veya Authorization header)
    if AGENT_API_KEY:
        tok = request.query_params.get("token", "")
        if not tok:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                tok = auth[7:]
        if tok != AGENT_API_KEY:
            raise HTTPException(status_code=401, detail="Token gerekli (?token=...)")


@app.get("/admin/dashboard")
async def admin_dashboard_html(request: Request):
    """Dashboard HTML sayfasi."""
    _dashboard_auth_check(request)
    from fastapi.responses import HTMLResponse
    html_path = Path(__file__).parent / "admin_dashboard.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="admin_dashboard.html bulunamadi")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/admin/dashboard/data")
async def admin_dashboard_data(request: Request, period: str = "today"):
    """Dashboard JSON veri — period: today|7d|30d|90d|all"""
    _dashboard_auth_check(request)
    try:
        from admin_dashboard import get_dashboard_data
        return await get_dashboard_data(period)
    except Exception as e:
        logger.error(f"Dashboard data hatasi: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── CLI Test Modu ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import uvicorn

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Hızlı test: python whatsapp_bridge.py test "Ahmet'i raporla"
        test_msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "yardım"

        async def _cli_test():
            print(f"\n📱 Test mesajı: {test_msg}")
            resp = await process_message("+905000000000", test_msg)
            print(f"\n🤖 Yanıt:\n{resp}")

        asyncio.run(_cli_test())
    else:
        uvicorn.run(
            "whatsapp_bridge:app",
            host="0.0.0.0",
            port=int(os.getenv("BRIDGE_PORT", "8001")),
            reload=os.getenv("DEV_MODE", "false").lower() == "true",
            log_level="info",
        )
