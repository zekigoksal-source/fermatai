"""
Continuous Learning Loop — Gerçek Öğrenen Sistem (23 Nisan)
==============================================================
Her cevap sonrası mikro feedback (👍/👎/emoji reaction).
Haftalık rapor → Neo onayıyla prompt ince ayar.
"""
from __future__ import annotations
from loguru import logger

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.feedback_events (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    role TEXT,
    message_id TEXT,
    conversation_id INT,
    signal TEXT NOT NULL,
    reason TEXT,
    response_snippet TEXT,
    handler_name TEXT,
    response_source TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fb_phone ON fermat.feedback_events(phone);
CREATE INDEX IF NOT EXISTS idx_fb_signal ON fermat.feedback_events(signal, created_at DESC);
"""


async def ensure_schema():
    try:
        from db_pool import db_execute
        for stmt in [s.strip() for s in CREATE_SQL.split(";") if s.strip()]:
            await db_execute(stmt)
    except Exception as e:
        logger.debug(f"fb schema: {e}")


async def log_feedback(phone: str, signal: str, reason: str = "",
                        response_snippet: str = "", handler_name: str = "",
                        response_source: str = "") -> bool:
    """Kullanıcı reaction/feedback kaydı.

    signal: 'thumbs_up' | 'thumbs_down' | 'tekrar_denedi' | 'konu_degistirdi' |
            'uzaklasti' | 'explicit_hata'
    """
    try:
        from db_pool import db_execute
        await db_execute(
            """
            INSERT INTO fermat.feedback_events
            (phone, signal, reason, response_snippet, handler_name, response_source)
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            phone, signal, reason[:300], response_snippet[:500], handler_name, response_source
        )
        return True
    except Exception as e:
        logger.debug(f"log_feedback: {e}")
        return False


async def detect_implicit_feedback(phone: str, prev_response: str, new_message: str) -> str | None:
    """Öğrencinin yeni mesajından implicit feedback çıkar.

    - "tekrar" / "bunu demedim" / "yanlış" → negatif
    - "tamam" / "anladım" / "evet" / "teşekkür" → pozitif
    - konu değişikliği → nötr
    """
    if not new_message:
        return None
    import re
    low = new_message.lower()
    if re.search(r'\b(yanl[ıi]ş|hata|anlam[aı]d[ıi]n|bunu\s*demedim|tekrar\s*dene|hayir|hayır|olmad[ıi])\b', low):
        return "thumbs_down"
    if re.search(r'\b(tesekkur|teşekkür|tamam|anladim|anladım|harika|super|süper|iyi\s*ki)\b', low):
        return "thumbs_up"
    return None


async def weekly_report() -> dict:
    """Son 7 gün feedback raporu (Neo'ya Pazartesi push)."""
    try:
        from db_pool import db_fetch
        rows = await db_fetch(
            """
            SELECT signal, COUNT(*) as c,
                   COUNT(DISTINCT phone) as kisi
            FROM fermat.feedback_events
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY signal
            """
        )
        summary = {r["signal"]: r["c"] for r in rows}
        up = summary.get("thumbs_up", 0)
        down = summary.get("thumbs_down", 0)
        total = sum(summary.values())
        return {
            "total": total,
            "positive": up,
            "negative": down,
            "sentiment_ratio": round(up / max(up + down, 1), 2),
            "all": summary,
        }
    except Exception as e:
        logger.debug(f"weekly_report: {e}")
        return {"total": 0}
