"""
Spaced Repetition Engine (Ebbinghaus eğrisi + Anki mantığı)
=============================================================
Öğrenci bir konu çözdü → 1g, 3g, 7g, 14g sonra mini test hatırlatma.
"""
from __future__ import annotations
from datetime import datetime, timedelta, date
from loguru import logger

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS fermat.spaced_repetition_queue (
    id SERIAL PRIMARY KEY,
    soz_no INTEGER NOT NULL,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    first_studied_at TIMESTAMP DEFAULT NOW(),
    next_review_at DATE,
    interval_day INT DEFAULT 1,
    ease_factor REAL DEFAULT 2.5,
    repetitions INT DEFAULT 0,
    status TEXT DEFAULT 'active',
    last_sent_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sr_nextreview ON fermat.spaced_repetition_queue(next_review_at, status);
CREATE INDEX IF NOT EXISTS idx_sr_soz_no ON fermat.spaced_repetition_queue(soz_no);
"""

SRS_INTERVALS = [1, 3, 7, 14, 30, 60, 120]  # days


async def ensure_schema():
    try:
        from db_pool import db_execute
        for stmt in [s.strip() for s in CREATE_SQL.split(";") if s.strip()]:
            await db_execute(stmt)
    except Exception as e:
        logger.debug(f"sr schema: {e}")


async def schedule_review(soz_no: int, ders: str, konu: str) -> bool:
    """Bir konu çalışıldı → kuyruğa al."""
    try:
        from db_pool import db_execute
        next_review = date.today() + timedelta(days=1)
        await db_execute(
            """
            INSERT INTO fermat.spaced_repetition_queue (soz_no, ders, konu, next_review_at, interval_day)
            VALUES ($1, $2, $3, $4, 1)
            """,
            soz_no, ders[:80], konu[:120], next_review
        )
        return True
    except Exception as e:
        logger.debug(f"schedule_review: {e}")
        return False


async def get_due_reviews(soz_no: int = None) -> list:
    """Bugün tekrar zamanı gelen konular (tüm öğrenciler VEYA belirli biri)."""
    try:
        from db_pool import db_fetch
        if soz_no:
            rows = await db_fetch(
                "SELECT id, soz_no, ders, konu, interval_day, repetitions FROM fermat.spaced_repetition_queue "
                "WHERE next_review_at <= CURRENT_DATE AND status='active' AND soz_no=$1 LIMIT 5",
                soz_no
            )
        else:
            rows = await db_fetch(
                "SELECT id, soz_no, ders, konu, interval_day, repetitions FROM fermat.spaced_repetition_queue "
                "WHERE next_review_at <= CURRENT_DATE AND status='active' "
                "AND (last_sent_at IS NULL OR last_sent_at < NOW() - INTERVAL '12 hours') LIMIT 100"
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"get_due: {e}")
        return []


async def mark_reviewed(review_id: int, success: bool = True) -> bool:
    """Öğrenci tekrar etti → sonraki intervali ayarla (SM-2 basit)."""
    try:
        from db_pool import db_fetchrow, db_execute
        row = await db_fetchrow(
            "SELECT interval_day, repetitions, ease_factor FROM fermat.spaced_repetition_queue WHERE id=$1",
            review_id
        )
        if not row:
            return False
        interval = row["interval_day"] or 1
        reps = row["repetitions"] or 0
        ef = row["ease_factor"] or 2.5

        if success:
            reps += 1
            if reps == 1:
                new_interval = 3
            elif reps == 2:
                new_interval = 7
            else:
                idx = min(reps, len(SRS_INTERVALS) - 1)
                new_interval = SRS_INTERVALS[idx]
            if reps >= 6:
                status = "mastered"
            else:
                status = "active"
        else:
            new_interval = 1  # reset
            reps = 0
            status = "active"

        next_review = date.today() + timedelta(days=new_interval)
        await db_execute(
            "UPDATE fermat.spaced_repetition_queue SET interval_day=$1, repetitions=$2, "
            "next_review_at=$3, status=$4, last_sent_at=NOW() WHERE id=$5",
            new_interval, reps, next_review, status, review_id
        )
        return True
    except Exception as e:
        logger.debug(f"mark_reviewed: {e}")
        return False


async def build_reminder_msg(soz_no: int, name: str) -> str | None:
    """Öğrenciye gönderilecek mini hatırlatma mesajı."""
    due = await get_due_reviews(soz_no)
    if not due:
        return None
    first = (name or "").split()[0] if name else ""
    msg = (
        f"📚 *{first}*, tekrar zamanı geldi!\n\n"
        f"Ebbinghaus unutma eğrisine göre bugün tekrarlaman gereken:\n\n"
    )
    for d in due[:3]:
        msg += f"  • *{d['ders']}* — {d['konu']}\n"
    msg += f"\n_Bir soru çöz veya kısa tekrar yap — 5 dakika yeter!_ 🎯"
    return msg
