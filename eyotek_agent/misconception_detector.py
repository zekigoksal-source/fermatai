"""
Misconception Detector (Oturum 25.29 — #7)
============================================

Yeni sezon (1 Eylul 2026) aktif olacak. Bu commit ALTYAPI HAZIR + FLAG KAPALI.

Mevcut altyapi (zaten var):
  - student_misconceptions table (adaptive_engine.py)
  - record_misconception() — pattern: aynı misc 7 gün içinde + confidence artır
  - get_active_misconceptions(soz_no, limit) — bekleyen misc listesi

Bu modul ekliyor:
  1. detect_from_conversation(soz_no, msg, bot_reply) — LLM ile misc cikar
  2. record_from_claude_tool(soz_no, ders, konu, misc, ornek)
       — bot conversation icinde fark ettiklerini kaydetsin
  3. teacher_misconception_brief(class_name, days)
       — sınıf bazli yaygin misconception listesi (rehber/ogretmen icin)
  4. student_active_misconceptions_for_prompt(soz_no, max_chars)
       — bot system_prompt'a inject (cevaplarken karsi argümanı bilsin)

Activation policy:
  MISCONCEPTION_TRACKER_ACTIVE = False
  Neo "yeni sezon misconception ac" derse veya 2026-09-01 sonrasi
  otomatik aktif. Mevcut sezonda fonksiyonlar None doner.
"""
from __future__ import annotations
import os
from datetime import date

from loguru import logger


# Aktivasyon kontrolu — environment veya tarih bazli
def is_active() -> bool:
    """Yeni sezon aktif mi? .env'de override edilebilir."""
    if os.getenv("MISCONCEPTION_TRACKER_ACTIVE", "false").lower() == "true":
        return True
    # Otomatik: 1 Eylul 2026 sonrasi
    today = date.today()
    return today >= date(2026, 9, 1)


# ─── 1. Conversation'dan misconception cikar ─────────────────────────────

# Yaygin YKS yanılgıları örnekleri (eğitim verisi olarak kullanılır)
COMMON_MISCONCEPTIONS_TEMPLATE = """
Yaygın YKS yanılgıları (referans):
- Fizik: "ışık dalga değil sadece tanecik" / "kuvvet hız üretir, ivme değil"
- Matematik: "sıfır asal sayıdır" / "0/0 = 0 veya 1"
- Kimya: "asit + baz = nötr (her zaman pH=7)"
- Biyoloji: "mitoz ve mayoz aynı şey" / "DNA = RNA"
- Türkçe: "anlam = düz anlam (yan anlam göz ardı)"
"""


async def detect_from_conversation(
    soz_no: int,
    user_msg: str,
    bot_reply: str = "",
    ders_hint: str = "",
    konu_hint: str = "",
) -> dict:
    """LLM ile mesajdan misconception cikar (conservative — sadece NET olanlari).

    Returns: {"detected": bool, "ders": ..., "konu": ..., "misconception": ...}
            veya {"detected": False, "reason": ...}
    """
    if not is_active():
        return {"detected": False, "reason": "tracker_inactive"}

    if not user_msg or len(user_msg) < 20:
        return {"detected": False, "reason": "msg_too_short"}

    # LLM cagrisi — Cerebras/Groq tercih (hizli + ucuz)
    try:
        from llm_router import LLMRouter
        router = LLMRouter()
    except Exception as e:
        logger.debug(f"[MISC] router init fail: {e}")
        return {"detected": False, "reason": "router_unavailable"}

    prompt = f"""Sen YKS müfredatına hakim bir egitim asistanısın.

Bir öğrencinin mesajını analiz et. ŞART: sadece NET, AÇIK bir kavram yanılgısı varsa raporla.
Belirsizse "Yok" de.

Öğrenci mesajı:
{user_msg[:500]}

{f"Bot cevabı: {bot_reply[:300]}" if bot_reply else ""}

{COMMON_MISCONCEPTIONS_TEMPLATE}

Yanıt formatı (JSON):
{{"yanilgi_var": true/false, "ders": "fizik/matematik/...", "konu": "...", "yanilgi": "..."}}

Net değilse: {{"yanilgi_var": false}}
"""
    try:
        resp = await router.chat_local(
            messages=[{"role": "user", "content": prompt}],
            system="Kavram yanılgısı tespit asistanısın. Sadece JSON yaz, başka şey yazma.",
            max_tokens=200,
        )
        if not resp or not isinstance(resp, str):
            return {"detected": False, "reason": "llm_empty"}

        import json as _json
        import re as _re
        # JSON extract
        m = _re.search(r"\{.*?\}", resp, _re.DOTALL)
        if not m:
            return {"detected": False, "reason": "no_json"}
        data = _json.loads(m.group(0))
        if not data.get("yanilgi_var"):
            return {"detected": False, "reason": "llm_said_no"}

        return {
            "detected": True,
            "ders": data.get("ders", ders_hint or ""),
            "konu": data.get("konu", konu_hint or ""),
            "misconception": data.get("yanilgi", "")[:300],
        }
    except Exception as e:
        logger.debug(f"[MISC] detect fail: {e}")
        return {"detected": False, "reason": f"error:{e}"}


# ─── 2. Claude tool wrapper ─────────────────────────────────────────────

async def record_from_claude_tool(
    soz_no: int,
    ders: str,
    konu: str,
    misconception: str,
    sample_question: str = "",
) -> dict:
    """Bot conversation icinde "anladım, ışığı sadece tanecik sanıyor" diye
    fark ederse bu tool'u çağırır. record_misconception'i sarar.
    """
    if not is_active():
        return {"recorded": False, "reason": "tracker_inactive"}

    try:
        from adaptive_engine import record_misconception
        result = await record_misconception(soz_no, ders, konu, misconception, sample_question)
        return {"recorded": True, **(result or {})}
    except Exception as e:
        return {"recorded": False, "error": str(e)[:200]}


# ─── 3. Ogretmen/rehber raporu ──────────────────────────────────────────

async def teacher_misconception_brief(
    class_name: str = "",
    days: int = 30,
    limit: int = 20,
) -> list[dict]:
    """Sınıfta yaygın yanılgılar (ders bazli grupla). Rehber/öğretmen için.

    Returns: [{ders, konu, misconception, occurrence_total, students_affected}]
    """
    if not is_active():
        return []

    from db_pool import db_fetch
    where_class = ""
    params = [str(days), int(limit)]
    if class_name:
        where_class = "AND s.class_name = $3"
        params.append(class_name)

    try:
        rows = await db_fetch(f"""
            SELECT m.ders, m.konu, m.misconception,
                   SUM(m.occurrence_count) AS occurrence_total,
                   COUNT(DISTINCT m.soz_no) AS students_affected
            FROM student_misconceptions m
            JOIN students s ON s.soz_no::text = m.soz_no::text
            WHERE m.resolved = false
              AND m.last_seen > NOW() - ($1 || ' days')::interval
              {where_class}
            GROUP BY m.ders, m.konu, m.misconception
            ORDER BY students_affected DESC, occurrence_total DESC
            LIMIT $2
        """, *params)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[MISC] brief fail: {e}")
        return []


# ─── 4. Student'a inject icin format ────────────────────────────────────

async def student_active_misconceptions_for_prompt(
    soz_no: int,
    max_chars: int = 500,
) -> str:
    """Ogrenci system_prompt'a eklenecek aktif misconception listesi.

    Bot biliyor olunca cevaplarken karsi argüman üretebilir.
    """
    if not is_active():
        return ""

    try:
        from adaptive_engine import get_active_misconceptions
        rows = await get_active_misconceptions(soz_no, limit=5)
        if not rows:
            return ""

        lines = ["📋 BU ÖĞRENCININ AKTİF YANILGILARI (cevaplarken dikkat et):"]
        for r in rows:
            lines.append(
                f"  • [{r.get('ders', '?')}/{r.get('konu', '?')}] "
                f"{(r.get('misconception') or '')[:100]} "
                f"(güven %{int((r.get('confidence', 0) or 0) * 100)})"
            )
        text = "\n".join(lines)
        return text[:max_chars]
    except Exception as e:
        logger.debug(f"[MISC] prompt format fail: {e}")
        return ""


# ─── CLI test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        print(f"is_active: {is_active()}")
        print(f"  (today = {date.today()}, threshold = 2026-09-01)")
        print()

        if not is_active():
            print("Tracker pasif — fonksiyonlar bos doner. Yeni sezon icin altyapi hazir.")
            return

        print("=== Detect test ===")
        result = await detect_from_conversation(
            137,
            "ışık tanecik mi yoksa dalga mı? Bence sadece tanecik olmalı.",
            "",
            "fizik",
            "ışık",
        )
        print(result)

    asyncio.run(_test())
