"""
FermatAI — student_insights merkezi log fonksiyonu (22.1n-neo)
================================================================

Tek giris noktasi — tum student_insights INSERT'leri buradan akmasi icin.
Eski log_* fonksiyonlari wrapper olarak kalir (backward compat), internal olarak
bu fonksiyonu cagirir.

KURAL (Neo 20 Nisan — fonksiyon tekrari yasak):
  Yeni bir "not/kayit/ozellik" eklerken ONCE buraya bak, varsa parametre ekle.

Tablo semasi: student_insights (id, soz_no, insight_type, content, confidence,
                                source, supersedes, created_at, resolved_at)
"""
from __future__ import annotations

import json
from typing import Optional

from loguru import logger

from db_pool import db_execute, db_fetchval


async def log_student_signal(
    soz_no: int,
    signal_type: str,
    content: str,
    confidence: float = 0.8,
    source: str = "",
    supersedes: Optional[int] = None,
) -> Optional[int]:
    """Student insights tablosuna tek giris.

    Args:
        soz_no: Ogrenci soz_no (INTEGER, students.soz_no TEXT oldugu icin int cast yap)
        signal_type: 'sentiment', 'insight', 'topic_discussed', 'teacher_escalation',
                     'memory', 'motivation', 'anxiety', 'target_change' vb.
        content: Kisa aciklama (max 500 char, otomatik kirpilir)
        confidence: 0.0-1.0, default 0.8
        source: 'sentiment_tracker', 'insight_extractor', 'teacher_escalation',
                'conversation_memory', 'fast_response', 'fermat_core_agent'
        supersedes: Eski kaydin id'si (time-decay icin, eski kaydi "ustune yaz")

    Returns:
        Yeni insight id'si (int) veya hata durumunda None.
    """
    if not soz_no or not signal_type or not content:
        return None
    try:
        soz_no = int(soz_no)
    except (TypeError, ValueError):
        logger.warning(f"log_student_signal: gecersiz soz_no={soz_no}")
        return None

    # TEST MODE GUARD (10 May Neo direktif): test mesajlari ogrenci insight'ina
    # yazilmasin — gercek profili kirletmesin, alarm tetiklemesin.
    try:
        from test_mode import is_test_context
        if is_test_context():
            logger.debug(f"[STUDENT_SIGNAL] test mode → skip (soz={soz_no}, type={signal_type})")
            return None
    except Exception:
        pass

    # Content boyutu sinirla (DB sinirini zorlama)
    if isinstance(content, (dict, list)):
        content = json.dumps(content, ensure_ascii=False)[:500]
    else:
        content = str(content)[:500]

    # 28 Nisan dedup: aynı (soz_no, signal_type, source) 30dk içinde tekrar
    # kaydedilmesin — Neo bulgu: TEHDIT testi 8+ kez kaydolmustu spam.
    try:
        recent = await db_fetchval(
            """SELECT id FROM student_insights
               WHERE soz_no = $1 AND insight_type = $2 AND source = $3
               AND created_at > NOW() - INTERVAL '30 minutes'
               LIMIT 1""",
            soz_no, signal_type, (source or "")[:60],
        )
        if recent:
            # Dedup: sadece last_seen_at güncelle, yeni satır YAZMA
            try:
                await db_execute(
                    "UPDATE student_insights SET last_seen_at=NOW() WHERE id=$1",
                    int(recent)
                )
            except Exception:
                pass
            return int(recent)
    except Exception:
        pass

    try:
        # Schema: id, soz_no, insight_type, content, source, confidence, is_active,
        # created_at, expires_at, active, stale_reason, superseded_by, last_seen_at, decay_score
        new_id = await db_fetchval(
            """INSERT INTO student_insights
               (soz_no, insight_type, content, confidence, source, created_at)
               VALUES ($1, $2, $3, $4, $5, NOW())
               RETURNING id""",
            soz_no, signal_type, content,
            float(confidence) if confidence is not None else 0.8,
            (source or "")[:60],
        )
        # supersedes parametresi geldiyse eski kaydin superseded_by alanini guncelle
        if new_id and supersedes:
            try:
                await db_execute(
                    "UPDATE student_insights SET active=FALSE, stale_reason='superseded', superseded_by=$1 WHERE id=$2",
                    new_id, int(supersedes)
                )
            except Exception:
                pass
        return int(new_id) if new_id is not None else None
    except Exception as e:
        logger.debug(f"log_student_signal hata: {e}")
        return None


async def resolve_signal(insight_id: int, reason: str = "") -> bool:
    """Insight'i resolved (bitmis) isaretle — time-decay icin.
    Schema 'resolved_at' yerine 'active=FALSE + stale_reason' kullanir."""
    if not insight_id:
        return False
    try:
        await db_execute(
            """UPDATE student_insights
               SET active=FALSE, stale_reason=COALESCE(NULLIF($1,''), 'resolved')
               WHERE id = $2""",
            reason, int(insight_id)
        )
        return True
    except Exception as e:
        logger.debug(f"resolve_signal hata: {e}")
        return False


# ── Backward compat alias'lar (eski kod bu isimlerle cagirabilsin) ────────
# Yeni kod log_student_signal kullanmali.
async def log_sentiment(soz_no: int, sentiment: str, content: str = "",
                         confidence: float = 0.8) -> Optional[int]:
    """Backward compat — sentiment_tracker eski API."""
    return await log_student_signal(
        soz_no, f"sentiment_{sentiment}", content or sentiment,
        confidence=confidence, source="sentiment_tracker"
    )


async def log_insight(soz_no: int, insight_type: str, content: str,
                      confidence: float = 0.7, supersedes: Optional[int] = None,
                      source: str = "insight_extractor") -> Optional[int]:
    """Backward compat — insight_extractor eski API."""
    return await log_student_signal(
        soz_no, insight_type, content,
        confidence=confidence, source=source, supersedes=supersedes
    )


async def log_topic_discussed(soz_no: int, ders: str, konu: str) -> Optional[int]:
    """Backward compat — conversation_memory Atlas #10 konu hafizasi."""
    content = json.dumps({"ders": ders, "konu": konu}, ensure_ascii=False)
    return await log_student_signal(
        soz_no, "topic_discussed", content,
        confidence=0.9, source="conversation_memory"
    )


async def log_teacher_escalation(soz_no: int, content: str, confidence: float = 0.9) -> Optional[int]:
    """Backward compat — teacher_escalation eski API."""
    return await log_student_signal(
        soz_no, "teacher_escalation", content,
        confidence=confidence, source="teacher_escalation"
    )
