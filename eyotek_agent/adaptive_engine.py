"""
Adaptive Intelligence Engine (Oturum 25.9, Neo karari)
=========================================================
3 katman:
  1. ELO Rating — her ogrenci × konu icin dinamik zorluk seviyesi
  2. SM-2 Spaced Repetition — konu tekrar zamanlamasi
  3. Misconception Detection — kavram yanılgısı tespit + takip

Her ogrenci konuda ne kadar usta? → ELO
Bu konuyu ne zaman tekrar etmeli? → SM-2
Hangi yanlislari tekrar tekrar yapiyor? → Misconception

Ogrenci soru cozdugunde / sinava girdiginde:
  observe_answer(soz_no, ders, konu, dogru, zorluk)
  → ELO update + SM-2 review schedule + (yanlissa) misconception detect

Ogrenciye "bugun ne calismaliyim" sorulduğunda:
  get_due_reviews(soz_no) → bugün/bu hafta tekrarlanmasi gereken konular
  get_weak_concepts(soz_no) → ELO < 1100 olan konular
  get_misconceptions(soz_no) → resolved=False kayitlar
"""
from __future__ import annotations
import asyncio
import math
import json
from datetime import date, datetime, timedelta
from typing import Optional, Literal

from loguru import logger

from db_pool import (
    db_execute as _exec,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)


# ── ELO RATING ─────────────────────────────────────────────────────────────

ELO_K_FACTOR = 32          # Maks rating degisimi tek soruda
ELO_DEFAULT = 1200         # Yeni baslangic
ELO_QUESTION_DIFFICULTY = {
    "kolay": 1000,
    "orta": 1200,
    "zor": 1500,
    "cok_zor": 1800,
}


def expected_score(player_rating: int, opponent_rating: int) -> float:
    """ELO beklenti: p(win) = 1 / (1 + 10^((opp-player)/400))"""
    return 1.0 / (1.0 + math.pow(10, (opponent_rating - player_rating) / 400.0))


async def update_elo(
    soz_no: int,
    ders: str,
    konu: str,
    dogru: bool,
    zorluk: str = "orta",
) -> dict:
    """Ogrenci sorudan sonra ELO'yu guncelle.

    Returns: {"old": 1200, "new": 1216, "delta": 16, "games": 5}
    """
    opp_rating = ELO_QUESTION_DIFFICULTY.get(zorluk, 1200)
    score = 1.0 if dogru else 0.0

    # Mevcut rating
    row = await _fetchrow(
        """SELECT rating, games_played FROM student_topic_elo
           WHERE soz_no=$1 AND ders=$2 AND konu=$3""",
        soz_no, ders, konu,
    )
    if row:
        old_rating = row['rating']
        games = row['games_played']
    else:
        old_rating = ELO_DEFAULT
        games = 0

    expected = expected_score(old_rating, opp_rating)
    new_rating = round(old_rating + ELO_K_FACTOR * (score - expected))
    new_rating = max(400, min(2400, new_rating))   # Clamp [400, 2400]

    await _exec(
        """INSERT INTO student_topic_elo (soz_no, ders, konu, rating, games_played, last_correct, last_updated)
           VALUES ($1, $2, $3, $4, 1, $5, NOW())
           ON CONFLICT (soz_no, ders, konu) DO UPDATE SET
             rating = EXCLUDED.rating,
             games_played = student_topic_elo.games_played + 1,
             last_correct = EXCLUDED.last_correct,
             last_updated = NOW()""",
        soz_no, ders, konu, new_rating, dogru,
    )

    return {
        "old": old_rating,
        "new": new_rating,
        "delta": new_rating - old_rating,
        "games": games + 1,
    }


async def get_elo_profile(soz_no: int, limit: int = 20) -> list[dict]:
    """Ogrencinin tüm konularda ELO durumu (en zayıftan güçlüye)."""
    rows = await _fetch(
        """SELECT ders, konu, rating, games_played, last_correct, last_updated
           FROM student_topic_elo WHERE soz_no=$1
           ORDER BY rating ASC, games_played DESC LIMIT $2""",
        soz_no, limit,
    )
    return [dict(r) for r in (rows or [])]


async def get_weak_concepts(soz_no: int, threshold: int = 1100, limit: int = 10) -> list[dict]:
    """ELO < threshold olan konular (zayıf alanlar)."""
    rows = await _fetch(
        """SELECT ders, konu, rating, games_played FROM student_topic_elo
           WHERE soz_no=$1 AND rating < $2 AND games_played >= 3
           ORDER BY rating ASC LIMIT $3""",
        soz_no, threshold, limit,
    )
    return [dict(r) for r in (rows or [])]


# ── SM-2 SPACED REPETITION ────────────────────────────────────────────────
# Klasik SuperMemo SM-2 algoritmasi
# Quality 0-5: 0=hic bilmedi, 5=mükemmel hatirladi
# 3+ → tekrar interval'i artar; <3 → sıfırlanır

def sm2_next(
    quality: int,
    repetitions: int,
    ease_factor: float,
    interval_days: int,
) -> tuple[int, float, int]:
    """SM-2 sonraki tekrar parametrelerini hesapla.

    Returns: (new_repetitions, new_ease_factor, new_interval_days)
    """
    quality = max(0, min(5, quality))

    if quality < 3:
        # Yanlış cevap — repetitions sıfırlanır, interval 1 gün
        return (0, max(1.3, ease_factor), 1)

    # Doğru cevap
    new_reps = repetitions + 1
    if new_reps == 1:
        new_interval = 1
    elif new_reps == 2:
        new_interval = 6
    else:
        new_interval = round(interval_days * ease_factor)

    # EF güncellemesi
    new_ef = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ef = max(1.3, new_ef)

    return (new_reps, new_ef, new_interval)


async def schedule_review(
    soz_no: int,
    ders: str,
    konu: str,
    quality: int,
) -> dict:
    """Konu tekrarini SM-2 ile zamanla.

    quality: 0-5 (5=mükemmel)
    Returns: {"next_date": date, "interval_days": int, "ease_factor": float}
    """
    # Mevcut zaman çizelgesi
    row = await _fetchrow(
        """SELECT id, repetitions, ease_factor, interval_days
           FROM student_review_schedule
           WHERE soz_no=$1 AND ders=$2 AND konu=$3
           ORDER BY id DESC LIMIT 1""",
        soz_no, ders, konu,
    )
    if row:
        reps = row['repetitions']
        ef = row['ease_factor']
        interval = row['interval_days']
        existing_id = row['id']
    else:
        reps = 0
        ef = 2.5
        interval = 1
        existing_id = None

    new_reps, new_ef, new_interval = sm2_next(quality, reps, ef, interval)
    next_date = date.today() + timedelta(days=new_interval)

    if existing_id:
        await _exec(
            """UPDATE student_review_schedule SET
                 repetitions=$1, ease_factor=$2, interval_days=$3,
                 next_review_date=$4, last_quality=$5, last_reviewed=NOW()
               WHERE id=$6""",
            new_reps, new_ef, new_interval, next_date, quality, existing_id,
        )
    else:
        await _exec(
            """INSERT INTO student_review_schedule
               (soz_no, ders, konu, repetitions, ease_factor, interval_days,
                next_review_date, last_quality, last_reviewed)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW())""",
            soz_no, ders, konu, new_reps, new_ef, new_interval, next_date, quality,
        )

    return {
        "next_date": next_date,
        "interval_days": new_interval,
        "ease_factor": round(new_ef, 2),
        "repetitions": new_reps,
    }


async def get_due_reviews(soz_no: int, days_ahead: int = 0) -> list[dict]:
    """Bugün veya N gün içinde tekrarlanması gereken konular."""
    target = date.today() + timedelta(days=days_ahead)
    rows = await _fetch(
        """SELECT ders, konu, interval_days, next_review_date, last_quality, repetitions
           FROM student_review_schedule
           WHERE soz_no=$1 AND next_review_date <= $2
           ORDER BY next_review_date ASC, repetitions DESC""",
        soz_no, target,
    )
    return [dict(r) for r in (rows or [])]


# ── MISCONCEPTION DETECTION ────────────────────────────────────────────────

async def record_misconception(
    soz_no: int,
    ders: str,
    konu: str,
    misconception: str,
    sample_question: Optional[str] = None,
) -> dict:
    """Bir kavram yanılgısını kaydet veya mevcudunu güçlendir.

    Aynı misconception 7 gün içinde tekrar görüldüyse confidence artır.
    """
    misconception = (misconception or "").strip()[:300]
    if not misconception:
        return {"error": "empty misconception"}

    # Mevcut kayit var mi (resolved=False)
    row = await _fetchrow(
        """SELECT id, confidence, occurrence_count, sample_questions FROM student_misconceptions
           WHERE soz_no=$1 AND ders=$2 AND konu=$3 AND misconception=$4
           AND resolved=FALSE
           ORDER BY id DESC LIMIT 1""",
        soz_no, ders, konu, misconception,
    )

    if row:
        new_count = row['occurrence_count'] + 1
        # Confidence: her gözlemde +0.1, max 1.0
        new_conf = min(1.0, row['confidence'] + 0.1)
        # Sample questions append (max 5)
        samples = row['sample_questions'] or []
        if isinstance(samples, str):
            try:
                samples = json.loads(samples)
            except Exception:
                samples = []
        if sample_question and len(samples) < 5:
            samples.append({"q": sample_question[:200], "ts": datetime.now().isoformat()})
        await _exec(
            """UPDATE student_misconceptions SET
                 occurrence_count=$1, confidence=$2, sample_questions=$3, last_seen=NOW()
               WHERE id=$4""",
            new_count, new_conf, json.dumps(samples), row['id'],
        )
        return {"id": row['id'], "occurrences": new_count, "confidence": new_conf, "updated": True}
    else:
        samples = [{"q": sample_question[:200], "ts": datetime.now().isoformat()}] if sample_question else []
        new_id = await _fetchval(
            """INSERT INTO student_misconceptions
               (soz_no, ders, konu, misconception, sample_questions)
               VALUES ($1,$2,$3,$4,$5) RETURNING id""",
            soz_no, ders, konu, misconception, json.dumps(samples),
        )
        return {"id": new_id, "occurrences": 1, "confidence": 0.5, "updated": False}


async def resolve_misconception(misconception_id: int) -> bool:
    """Bir misconception'u cozulmus olarak isaretle."""
    await _exec(
        """UPDATE student_misconceptions SET resolved=TRUE, resolved_at=NOW()
           WHERE id=$1""",
        misconception_id,
    )
    return True


async def get_active_misconceptions(soz_no: int, limit: int = 5) -> list[dict]:
    """Ogrencinin aktif (cozulmemis) kavram yanılgıları."""
    rows = await _fetch(
        """SELECT id, ders, konu, misconception, confidence, occurrence_count, last_seen
           FROM student_misconceptions
           WHERE soz_no=$1 AND resolved=FALSE
           ORDER BY confidence DESC, occurrence_count DESC LIMIT $2""",
        soz_no, limit,
    )
    return [dict(r) for r in (rows or [])]


# ── HIGH-LEVEL ORCHESTRATION ────────────────────────────────────────────────

async def observe_answer(
    soz_no: int,
    ders: str,
    konu: str,
    dogru: bool,
    zorluk: str = "orta",
    quality: Optional[int] = None,
    misconception: Optional[str] = None,
    sample_question: Optional[str] = None,
) -> dict:
    """Tek cagri ile 3 katmani da guncelle:
       1. ELO update
       2. SM-2 schedule
       3. Misconception kayit (yanlissa + misconception verildiyse)

    quality verilmediyse dogru=True->4, dogru=False->1 default
    """
    if quality is None:
        quality = 4 if dogru else 1

    elo_result = await update_elo(soz_no, ders, konu, dogru, zorluk)
    sm2_result = await schedule_review(soz_no, ders, konu, quality)

    misc_result = None
    if not dogru and misconception:
        misc_result = await record_misconception(soz_no, ders, konu, misconception, sample_question)

    return {
        "elo": elo_result,
        "review": sm2_result,
        "misconception": misc_result,
    }


async def get_adaptive_summary(soz_no: int) -> dict:
    """Ogrenci icin adaptive intelligence ozeti — bot context'e eklenmek icin.

    Returns: {
      "weak_topics": [{ders, konu, rating}],
      "due_today": [{ders, konu, interval_days}],
      "active_misconceptions": [{ders, konu, misconception, confidence}],
      "total_topics_studied": N,
      "avg_rating": 1180,
    }
    """
    weak, due, misc, stats = await asyncio.gather(
        get_weak_concepts(soz_no, threshold=1100, limit=5),
        get_due_reviews(soz_no, days_ahead=0),
        get_active_misconceptions(soz_no, limit=3),
        _fetchrow(
            """SELECT COUNT(*) as cnt, AVG(rating)::INT as avg_r
               FROM student_topic_elo WHERE soz_no=$1""",
            soz_no,
        ),
        return_exceptions=True,
    )

    if isinstance(weak, Exception): weak = []
    if isinstance(due, Exception): due = []
    if isinstance(misc, Exception): misc = []

    cnt = (stats.get('cnt', 0) if isinstance(stats, dict) or hasattr(stats, 'get') else 0) if not isinstance(stats, Exception) else 0
    avg_r = (stats.get('avg_r', 1200) if isinstance(stats, dict) or hasattr(stats, 'get') else 1200) if not isinstance(stats, Exception) else 1200

    return {
        "weak_topics": weak,
        "due_today": due,
        "active_misconceptions": misc,
        "total_topics_studied": cnt or 0,
        "avg_rating": avg_r or 1200,
    }


if __name__ == "__main__":
    # Smoke test
    async def _t():
        # Test ELO math
        e = expected_score(1200, 1500)
        print(f"Expected score (1200 vs 1500): {e:.3f} (should be ~0.15)")

        # Test SM-2 progression
        reps, ef, interval = 0, 2.5, 1
        for i, q in enumerate([5, 4, 5, 3, 5]):
            reps, ef, interval = sm2_next(q, reps, ef, interval)
            print(f"Q{i+1}={q}: reps={reps} ef={ef:.2f} interval={interval}d")

    asyncio.run(_t())
