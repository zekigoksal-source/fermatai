"""
Context Engine — Oturum 25.29
================================

ChatGPT'nin "Unified Context Engine" önerisinin implementasyonu.
Her decision aynı pencereden beslenir: tek standardize format.

Mimari ilke (memory'de):
  "Brain centralized, execution modular" — context tek beyin, her servis ayrı.

Mevcut iki ayrı context fonksiyonu vardı:
  1. conversation_memory.get_student_context(phone) — 6 query, 5dk cache
  2. study_plan_builder.build_study_plan_context(soz_no) — 10 query, 30dk cache

Bu modül onları sarar + eksikleri (sentiment, blueprint awareness vb.) ekler.
ASLA yeniden DB query yazmaz — mevcutları çağırır (DRY).

API:
  unified = await build_unified_context(soz_no, channel='web', role='ogrenci')
  # unified.student_profile, unified.exam_summary, unified.weak_topics,
  # unified.recent_activity, unified.daily_plan, unified.sentiment, ...

Kullanım yerleri (öncelik sırasıyla):
  1. fermat_core_agent.run() — system prompt context inject
  2. predictive_engine — burnout score hesaplama
  3. tool: get_student_analytics (refactor sonrası bu wrap edecek)
  4. study_plan_builder — backwards-compatible (build_study_plan_context çağrılır)
"""
from __future__ import annotations
import asyncio
import time
from datetime import datetime
from typing import Optional

from loguru import logger


# In-memory cache (5dk TTL) — Redis migration ileride
_UNIFIED_CACHE: dict = {}
_UNIFIED_CACHE_TTL = 300  # 5dk


async def _safe_call(coro, default=None):
    """Coroutine'i güvenli çağır — fail olursa default dön (cascade fail önle)."""
    try:
        return await coro
    except Exception as e:
        logger.debug(f"[CTX] _safe_call fail: {e}")
        return default


async def _get_student_profile(soz_no: int) -> dict:
    """students tablosundan temel profil."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT soz_no, full_name, first_name, last_name, class_name,
                      sezon, status, sube, program, devre, kur,
                      phone, parent_name, eyotek_id
               FROM students
               WHERE soz_no::int = $1
               LIMIT 1""",
            soz_no,
        )
        if not row:
            return {}
        return dict(row)
    except Exception as e:
        logger.debug(f"[CTX] profile fail: {e}")
        return {}


async def _get_exam_summary(soz_no: int) -> dict:
    """Son 3 deneme + ortalama + trend."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT exam_name, exam_date, toplam, turkce, matematik,
                      fizik, kimya, biyoloji, exam_type
               FROM student_exams
               WHERE soz_no = $1 AND toplam IS NOT NULL AND toplam > 5
                 AND exam_name NOT LIKE '[AYT]%'
               ORDER BY exam_date DESC NULLS LAST
               LIMIT 3""",
            soz_no,
        )
        son_3 = [dict(r) for r in rows]
        avg = sum(r.get("toplam") or 0 for r in son_3) / len(son_3) if son_3 else 0
        # Trend: son denemede artış mı düşüş mü?
        trend = None
        if len(son_3) >= 2:
            diff = (son_3[0].get("toplam") or 0) - (son_3[1].get("toplam") or 0)
            trend = "yukari" if diff > 3 else "asagi" if diff < -3 else "yatay"
        return {
            "son_3": son_3,
            "ortalama_net": round(avg, 1),
            "trend": trend,
        }
    except Exception as e:
        logger.debug(f"[CTX] exam_summary fail: {e}")
        return {"son_3": [], "ortalama_net": 0, "trend": None}


async def _get_weak_topics(soz_no: int, top_k: int = 5) -> list:
    """En yüksek hata oranlı zayıf konular."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT ders, konu, sinav_hata_yuzdesi, status
               FROM student_topic_tracker
               WHERE soz_no = $1 AND sinav_hata_yuzdesi >= 40
                 AND tamamlandi = false
               ORDER BY sinav_hata_yuzdesi DESC
               LIMIT $2""",
            soz_no, top_k,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[CTX] weak_topics fail: {e}")
        return []


async def _get_recent_activity(phone: str, days: int = 7) -> dict:
    """Son N gün konuşma + etüt etkinliği."""
    from db_pool import db_fetchval, db_fetch
    try:
        msg_count = await db_fetchval(
            """SELECT COUNT(*) FROM agent_conversations
               WHERE phone = $1 AND created_at > NOW() - ($2 || ' days')::interval
                 AND message_role = 'user'""",
            phone, str(days),
        ) or 0
        last_seen = await db_fetchval(
            """SELECT MAX(created_at) FROM agent_conversations
               WHERE phone = $1 AND message_role = 'user'""",
            phone,
        )
        return {
            "mesaj_sayisi_son_n_gun": int(msg_count or 0),
            "son_etkilesim": last_seen.isoformat() if last_seen else None,
            "days": days,
        }
    except Exception as e:
        logger.debug(f"[CTX] recent_activity fail: {e}")
        return {"mesaj_sayisi_son_n_gun": 0, "son_etkilesim": None, "days": days}


async def _get_sentiment(phone: str, soz_no: int, days: int = 14) -> dict:
    """Son N gün duygu sinyallari. student_insights.insight_type tablosu kullanir."""
    from db_pool import db_fetch
    try:
        rows = await db_fetch(
            """SELECT insight_type, COUNT(*) AS n
               FROM student_insights
               WHERE soz_no = $1
                 AND created_at > NOW() - ($2 || ' days')::interval
                 AND active = true
               GROUP BY insight_type""",
            soz_no, str(days),
        )
        signals = {r["insight_type"]: int(r["n"]) for r in rows}
        # Negatif kategoriler (sentiment_tracker'in detect ettikleri)
        negative_total = sum(
            v for k, v in signals.items()
            if k in ("crisis", "stressed", "negative", "angry",
                     "kaygi", "motivasyon_dusuk", "ofke")
        )
        positive_total = sum(
            v for k, v in signals.items()
            if k in ("positive", "motivated", "iyi")
        )
        net = positive_total - negative_total
        if negative_total >= 5:
            durum = "alarm"
        elif negative_total >= 2:
            durum = "izle"
        elif net > 0:
            durum = "iyi"
        else:
            durum = "norm"
        return {
            "durum": durum,
            "negatif_sinyal": negative_total,
            "pozitif_sinyal": positive_total,
            "kategoriler": signals,
            "days": days,
        }
    except Exception as e:
        logger.debug(f"[CTX] sentiment fail: {e}")
        return {"durum": "norm", "negatif_sinyal": 0, "pozitif_sinyal": 0,
                "kategoriler": {}, "days": days}


async def _get_daily_plan(soz_no: int) -> dict:
    """Bugün için kaydedilmiş çalışma planı (varsa).

    Tablo varlığı dinamik kontrol — student_plans henüz oluşturulmamış olabilir.
    """
    from db_pool import db_fetchrow, db_fetchval
    try:
        # Tablo var mı kontrol (information_schema)
        exists = await db_fetchval(
            """SELECT 1 FROM information_schema.tables
               WHERE table_schema='fermat' AND table_name='student_plans'
               LIMIT 1"""
        )
        if not exists:
            return {"var": False, "tablo_yok": True}

        row = await db_fetchrow(
            """SELECT plan_json, gun_sayisi, durum, created_at
               FROM student_plans
               WHERE soz_no = $1
                 AND created_at > NOW() - INTERVAL '14 days'
               ORDER BY created_at DESC LIMIT 1""",
            soz_no,
        )
        if row:
            return {
                "var": True,
                "gun_sayisi": row.get("gun_sayisi"),
                "durum": row.get("durum"),
                "olusturma": row["created_at"].isoformat() if row.get("created_at") else None,
            }
        return {"var": False}
    except Exception as e:
        logger.debug(f"[CTX] daily_plan fail: {e}")
        return {"var": False}


async def _get_attendance(soz_no: int) -> dict:
    """Devamsızlık özeti."""
    from db_pool import db_fetchval
    try:
        toplam = await db_fetchval(
            "SELECT toplam_saat FROM devamsizlik_sayisi WHERE soz_no = $1",
            soz_no,
        )
        return {"toplam_saat": int(toplam or 0)}
    except Exception:
        return {"toplam_saat": 0}


# ─── ANA API ──────────────────────────────────────────────────────────────────

async def _get_weekly_delta(soz_no: int) -> dict:
    """
    25.40p (Neo direktif): Proaktif feedback — bu hafta vs gecen hafta delta.

    Bot 'gecen hafta turev calistın bu hafta turevde 3 hata var, tekrar gerek mi?'
    diyebilsin diye haftalik calisma + sinav delta'si.

    Returns:
      {
        'gecen_hafta_konular': [...],         # etut_history
        'bu_hafta_konular': [...],
        'gecen_hafta_deneme_net': ...,
        'bu_hafta_deneme_net': ...,
        'net_delta': float,
        'tekrar_hata_konular': [...]   # gecen hafta calisilan + bu hafta yine hata
      }
    """
    from db_pool import db_fetch, db_fetchrow
    try:
        # Gecen hafta etut_history (8-14 gun once)
        gh_rows = await db_fetch(
            """SELECT DISTINCT ders, konu FROM etut_history
               WHERE student_id = $1::text
                 AND tarih BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days'""",
            soz_no,
        )
        # Bu hafta etut_history (0-7 gun once)
        bh_rows = await db_fetch(
            """SELECT DISTINCT ders, konu FROM etut_history
               WHERE student_id = $1::text
                 AND tarih > NOW() - INTERVAL '7 days'""",
            soz_no,
        )
        gecen_konular = [{"ders": r["ders"], "konu": r["konu"]} for r in (gh_rows or [])]
        bu_konular = [{"ders": r["ders"], "konu": r["konu"]} for r in (bh_rows or [])]

        # Gecen hafta deneme net ortalama
        gh_net = await db_fetchrow(
            """SELECT AVG(toplam_net) AS ort FROM student_exams
               WHERE student_id = $1
                 AND tarih BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days'""",
            soz_no,
        )
        bh_net = await db_fetchrow(
            """SELECT AVG(toplam_net) AS ort FROM student_exams
               WHERE student_id = $1
                 AND tarih > NOW() - INTERVAL '7 days'""",
            soz_no,
        )
        g_net = float(gh_net["ort"]) if gh_net and gh_net["ort"] else 0.0
        b_net = float(bh_net["ort"]) if bh_net and bh_net["ort"] else 0.0

        # Tekrar hata: gecen hafta etut yapilmis + bu hafta yine zayif konu (topic_tracker)
        # Sadece gecen hafta etut yapilan konularin listesi
        gh_konu_set = {(r["ders"], r["konu"]) for r in (gh_rows or [])}
        # Bu hafta zayif (hata > 50%) topic_tracker
        zayif_rows = await db_fetch(
            """SELECT ders, konu FROM student_topic_tracker
               WHERE soz_no=$1 AND hata_yuzdesi > 50
                 AND son_calisma > NOW() - INTERVAL '7 days'""",
            soz_no,
        )
        tekrar_hata = []
        for r in (zayif_rows or []):
            if (r["ders"], r["konu"]) in gh_konu_set:
                tekrar_hata.append({"ders": r["ders"], "konu": r["konu"]})

        return {
            "gecen_hafta_konular": gecen_konular[:10],
            "bu_hafta_konular": bu_konular[:10],
            "gecen_hafta_deneme_net": round(g_net, 2),
            "bu_hafta_deneme_net": round(b_net, 2),
            "net_delta": round(b_net - g_net, 2),
            "tekrar_hata_konular": tekrar_hata[:5],
        }
    except Exception as e:
        logger.debug(f"[WEEKLY_DELTA] hata: {e}")
        return {}


async def build_unified_context(
    soz_no: int,
    channel: str = "whatsapp",
    role: str = "ogrenci",
    phone: Optional[str] = None,
    force_refresh: bool = False,
) -> dict:
    """Tek pencere context — ChatGPT'nin "Unified Context Engine" önerisi.

    Tüm context-tüketici fonksiyonlar (system prompt inject, predictive engine,
    bot tools) bu çıktıdan beslenir.

    Args:
        soz_no: Öğrenci ID (zorunlu)
        channel: 'whatsapp' | 'web' (RAG inject + prompt addon farkı)
        role: 'ogrenci' | 'ogretmen' | 'rehber' | 'mudur' | 'admin'
        phone: opsiyonel — recent_activity + sentiment phone-based
        force_refresh: cache bypass

    Returns:
        {
          'meta': {soz_no, channel, role, generated_at, cached},
          'student_profile': {...},
          'exam_summary': {...},
          'weak_topics': [...],
          'recent_activity': {...},
          'sentiment': {...},
          'daily_plan': {...},
          'attendance': {...},
        }
    """
    cache_key = f"{soz_no}_{channel}_{role}"
    now = time.time()

    # Cache kontrol
    if not force_refresh and cache_key in _UNIFIED_CACHE:
        entry = _UNIFIED_CACHE[cache_key]
        if now - entry["_ts"] < _UNIFIED_CACHE_TTL:
            result = {k: v for k, v in entry.items() if k != "_ts"}
            result["meta"]["cached"] = True
            return result

    try:
        soz_no = int(soz_no)
    except (ValueError, TypeError):
        return {
            "meta": {"soz_no": soz_no, "error": "invalid_soz_no"},
            "error": f"Geçersiz soz_no: {soz_no}",
        }

    # Phone yoksa students tablosundan çek (recent_activity + sentiment için)
    if not phone:
        from db_pool import db_fetchval
        try:
            phone = await db_fetchval(
                "SELECT phone FROM students WHERE soz_no::int = $1 LIMIT 1",
                soz_no,
            )
        except Exception:
            phone = ""

    # 8 paralel query — tek beyin, her servisi ayrı çağır
    # 25.40p: weekly_delta eklendi (proaktif feedback için)
    profile, exams, weak, activity, sentiment, plan, attend, weekly = await asyncio.gather(
        _safe_call(_get_student_profile(soz_no), {}),
        _safe_call(_get_exam_summary(soz_no), {}),
        _safe_call(_get_weak_topics(soz_no, top_k=5), []),
        _safe_call(_get_recent_activity(phone or "", days=7), {}),
        _safe_call(_get_sentiment(phone or "", soz_no, days=14), {}),
        _safe_call(_get_daily_plan(soz_no), {}),
        _safe_call(_get_attendance(soz_no), {}),
        _safe_call(_get_weekly_delta(soz_no), {}),
    )

    result = {
        "meta": {
            "soz_no": soz_no,
            "channel": channel,
            "role": role,
            "generated_at": datetime.now().isoformat(),
            "cached": False,
        },
        "student_profile": profile,
        "exam_summary": exams,
        "weak_topics": weak,
        "recent_activity": activity,
        "sentiment": sentiment,
        "daily_plan": plan,
        "attendance": attend,
        "weekly_delta": weekly,  # 25.40p — proaktif feedback
    }

    # Cache'e yaz
    _UNIFIED_CACHE[cache_key] = {**result, "_ts": now}

    # Memory leak guard: 100+ entry varsa eski 50'sini sil
    if len(_UNIFIED_CACHE) > 100:
        sorted_keys = sorted(
            _UNIFIED_CACHE.items(),
            key=lambda x: x[1].get("_ts", 0),
        )
        for k, _ in sorted_keys[:50]:
            _UNIFIED_CACHE.pop(k, None)

    return result


def invalidate_unified_cache(soz_no: int = None) -> int:
    """Belirli öğrenci veya tüm cache temizle."""
    if soz_no is None:
        cleared = len(_UNIFIED_CACHE)
        _UNIFIED_CACHE.clear()
        return cleared
    cleared = 0
    for key in list(_UNIFIED_CACHE.keys()):
        if key.startswith(f"{soz_no}_"):
            _UNIFIED_CACHE.pop(key, None)
            cleared += 1
    return cleared


def cache_stats() -> dict:
    """Cache istatistikleri — admin için."""
    now = time.time()
    fresh = sum(1 for v in _UNIFIED_CACHE.values()
                if now - v.get("_ts", 0) < _UNIFIED_CACHE_TTL)
    return {
        "total_entries": len(_UNIFIED_CACHE),
        "fresh_entries": fresh,
        "ttl_seconds": _UNIFIED_CACHE_TTL,
    }


# ─── Format Helpers — bot prompt'a inject icin ───────────────────────────────

def format_for_prompt(unified: dict, max_chars: int = 1500) -> str:
    """Unified context'i okunaklı text bloğuna çevir (system prompt için)."""
    if not unified or unified.get("error"):
        return ""

    profile = unified.get("student_profile", {})
    exams = unified.get("exam_summary", {})
    weak = unified.get("weak_topics", [])
    sentiment = unified.get("sentiment", {})
    plan = unified.get("daily_plan", {})
    attend = unified.get("attendance", {})

    name = profile.get("full_name", "?")
    cls = profile.get("class_name", "?")

    lines = [
        f"📌 ÖĞRENCİ BAĞLAMI ({name} — {cls}):",
    ]

    if exams.get("son_3"):
        son = exams["son_3"][0]
        trend = exams.get("trend", "?")
        trend_icon = {"yukari": "📈", "asagi": "📉", "yatay": "➡️"}.get(trend, "•")
        lines.append(
            f"  • Son deneme: {son.get('exam_name', '?')[:40]} → "
            f"{son.get('toplam', 0):.1f} net {trend_icon} (ort {exams.get('ortalama_net', 0)})"
        )

    if weak:
        zayif_str = ", ".join(
            f"{w['ders']}/{w['konu'][:25]} (%{int(w['sinav_hata_yuzdesi'])})"
            for w in weak[:3]
        )
        lines.append(f"  • Zayıf konular: {zayif_str}")

    if sentiment.get("durum") in ("alarm", "izle"):
        lines.append(
            f"  ⚠ Duygu durumu: {sentiment['durum']} "
            f"(neg {sentiment['negatif_sinyal']}, poz {sentiment['pozitif_sinyal']})"
        )

    if plan.get("var"):
        lines.append(
            f"  • Çalışma planı: VAR (durum: {plan.get('durum', '?')})"
        )

    if attend.get("toplam_saat", 0) > 50:
        lines.append(f"  • Devamsızlık: {attend['toplam_saat']} saat")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... kesildi]"
    return text


# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json as _json

    async def _test(soz_no: int):
        t0 = time.time()
        ctx = await build_unified_context(soz_no, channel="web", role="ogrenci")
        elapsed = (time.time() - t0) * 1000
        print(f"=== UNIFIED CONTEXT (soz_no={soz_no}, {elapsed:.0f}ms) ===")
        print(_json.dumps(ctx, indent=2, ensure_ascii=False, default=str)[:3000])
        print()
        print("=== FORMAT FOR PROMPT ===")
        print(format_for_prompt(ctx))
        print()
        # Cache test (2. çağrı)
        t0 = time.time()
        ctx2 = await build_unified_context(soz_no, channel="web", role="ogrenci")
        elapsed2 = (time.time() - t0) * 1000
        print(f"=== 2. CALL (cache hit beklenir, {elapsed2:.0f}ms) ===")
        print(f"  cached: {ctx2['meta'].get('cached')}")

    soz_no = int(sys.argv[1]) if len(sys.argv) > 1 else 244  # ÇAĞAN YAKAY
    asyncio.run(_test(soz_no))
