"""
Öğrenci Günlük Takip — CRUD + Analiz Helper
================================================
Oturum 25.12 — GRAFEN-tarzı 7 modül için backend.

Modüller:
  1. daily_program — saatli ders/aktivite blokları
  2. todo — yapılacaklar listesi
  3. habits — günlük tekrarlanan rutinler
  4. exam_calendar — yaklaşan sınav/ödev
  5. study_stats — günlük süre + soru sayısı
  6. physical_activity — egzersiz takibi
  7. daily_notes — bugüne notum + mood

KULLANIM:
  from student_daily import (
      add_daily_program, get_daily_program,
      add_todo, complete_todo,
      log_study_session, get_weekly_stats,
      add_daily_note, get_summary,
  )

KVKK: Tüm fonksiyonlar soz_no ile filtrelenir. Caller fermat_core_agent
ACL kontrolünü yapar — bot sadece kendi öğrencisinin verisine erişir.
"""
from __future__ import annotations
import asyncio
import json
from datetime import date, datetime, timedelta, time as dtime
from typing import Optional, Any

from loguru import logger

from db_pool import (
    db_execute as _exec,
    db_fetch as _fetch,
    db_fetchrow as _fetchrow,
    db_fetchval as _fetchval,
)


# ── 1. GÜNLÜK PROGRAM ───────────────────────────────────────────────────

async def add_daily_program(
    soz_no: int,
    title: str,
    start_time: str,                # "09:00"
    end_time: Optional[str] = None,  # "10:00"
    plan_date: Optional[date] = None,
    ders: Optional[str] = None,
    konu: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Günlük programa yeni blok ekle."""
    plan_date = plan_date or date.today()
    nid = await _fetchval(
        """INSERT INTO student_daily_program
           (soz_no, plan_date, start_time, end_time, title, ders, konu, notes)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
        soz_no, plan_date, start_time, end_time,
        title[:200], ders, konu, notes,
    )
    return {"id": nid, "title": title, "plan_date": str(plan_date)}


async def get_daily_program(soz_no: int, plan_date: Optional[date] = None) -> list[dict]:
    """Bir günün programı (default bugün)."""
    plan_date = plan_date or date.today()
    rows = await _fetch(
        """SELECT id, start_time::text, end_time::text, title, ders, konu, completed, notes
           FROM student_daily_program
           WHERE soz_no=$1 AND plan_date=$2
           ORDER BY start_time""",
        soz_no, plan_date,
    )
    return [dict(r) for r in (rows or [])]


async def complete_program_block(block_id: int, soz_no: int) -> bool:
    """Bloğu tamamlandı işaretle (ACL: soz_no eşleşmeli)."""
    result = await _exec(
        """UPDATE student_daily_program SET completed=TRUE, updated_at=NOW()
           WHERE id=$1 AND soz_no=$2""",
        block_id, soz_no,
    )
    return True


async def delete_program_block(block_id: int, soz_no: int) -> bool:
    await _exec(
        "DELETE FROM student_daily_program WHERE id=$1 AND soz_no=$2",
        block_id, soz_no,
    )
    return True


# ── 2. TO DO LIST ───────────────────────────────────────────────────────

async def add_todo(
    soz_no: int,
    title: str,
    due_date: Optional[date] = None,
    priority: str = "normal",
) -> dict:
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"
    nid = await _fetchval(
        """INSERT INTO student_todo (soz_no, title, due_date, priority)
           VALUES ($1,$2,$3,$4) RETURNING id""",
        soz_no, title[:200], due_date, priority,
    )
    return {"id": nid, "title": title, "priority": priority}


async def get_todos(soz_no: int, only_open: bool = True) -> list[dict]:
    where = "soz_no=$1" + (" AND completed=FALSE" if only_open else "")
    rows = await _fetch(
        f"""SELECT id, title, due_date, priority, completed, completed_at, created_at
            FROM student_todo
            WHERE {where}
            ORDER BY (priority='urgent') DESC, (priority='high') DESC,
                     due_date ASC NULLS LAST, created_at DESC""",
        soz_no,
    )
    return [dict(r) for r in (rows or [])]


async def complete_todo(todo_id: int, soz_no: int) -> bool:
    await _exec(
        """UPDATE student_todo SET completed=TRUE, completed_at=NOW()
           WHERE id=$1 AND soz_no=$2""",
        todo_id, soz_no,
    )
    return True


async def delete_todo(todo_id: int, soz_no: int) -> bool:
    await _exec(
        "DELETE FROM student_todo WHERE id=$1 AND soz_no=$2",
        todo_id, soz_no,
    )
    return True


# ── 3. ALIŞKANLIK TAKİBİ ────────────────────────────────────────────────

async def add_habit(
    soz_no: int,
    habit_name: str,
    target_days: Optional[list[str]] = None,  # ['Pzt','Sal',...]
) -> dict:
    target_days = target_days or ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
    nid = await _fetchval(
        """INSERT INTO student_habits (soz_no, habit_name, target_days)
           VALUES ($1,$2,$3) RETURNING id""",
        soz_no, habit_name[:120], target_days,
    )
    return {"id": nid, "habit_name": habit_name}


async def get_habits(soz_no: int, active_only: bool = True) -> list[dict]:
    where = "soz_no=$1" + (" AND is_active=TRUE" if active_only else "")
    rows = await _fetch(
        f"""SELECT id, habit_name, target_days, streak, longest_streak, created_at
            FROM student_habits WHERE {where} ORDER BY created_at DESC""",
        soz_no,
    )
    items = [dict(r) for r in (rows or [])]

    # Her habit için son 7 gün log
    for h in items:
        logs = await _fetch(
            """SELECT log_date, completed FROM student_habit_log
               WHERE habit_id=$1 AND log_date >= CURRENT_DATE - INTERVAL '6 days'
               ORDER BY log_date""",
            h["id"],
        )
        h["recent_7d"] = [{"date": str(l["log_date"]), "done": l["completed"]} for l in (logs or [])]
    return items


async def log_habit(habit_id: int, log_date: Optional[date] = None, completed: bool = True, note: Optional[str] = None) -> dict:
    """Bugün için habit log gir/güncelle. Streak güncelle."""
    log_date = log_date or date.today()
    await _exec(
        """INSERT INTO student_habit_log (habit_id, log_date, completed, note)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (habit_id, log_date) DO UPDATE SET
             completed=EXCLUDED.completed, note=EXCLUDED.note""",
        habit_id, log_date, completed, note,
    )
    # Streak hesabı (basit: son ardışık tamamlanma sayısı)
    rows = await _fetch(
        """SELECT log_date, completed FROM student_habit_log
           WHERE habit_id=$1 ORDER BY log_date DESC LIMIT 60""",
        habit_id,
    )
    streak = 0
    for r in (rows or []):
        if r["completed"]:
            streak += 1
        else:
            break
    longest = await _fetchval(
        "SELECT longest_streak FROM student_habits WHERE id=$1", habit_id
    ) or 0
    new_longest = max(longest, streak)
    await _exec(
        "UPDATE student_habits SET streak=$1, longest_streak=$2 WHERE id=$3",
        streak, new_longest, habit_id,
    )
    return {"streak": streak, "longest": new_longest}


# ── 4. SINAV/ÖDEV TAKVİMİ ───────────────────────────────────────────────

async def add_exam_event(
    soz_no: int,
    title: str,
    event_date: date,
    event_type: str = "sinav",
    event_time: Optional[str] = None,
    ders: Optional[str] = None,
) -> dict:
    if event_type not in ("sinav", "odev", "etut", "rehberlik"):
        event_type = "sinav"
    nid = await _fetchval(
        """INSERT INTO student_exam_calendar
           (soz_no, title, event_type, event_date, event_time, ders)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        soz_no, title[:200], event_type, event_date, event_time, ders,
    )
    return {"id": nid, "title": title, "event_date": str(event_date)}


async def get_upcoming_events(soz_no: int, days_ahead: int = 30) -> list[dict]:
    rows = await _fetch(
        f"""SELECT id, title, event_type, event_date, event_time::text, ders, completed, score
            FROM student_exam_calendar
            WHERE soz_no=$1
              AND event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '{int(days_ahead)} days'
            ORDER BY event_date, event_time""",
        soz_no,
    )
    return [dict(r) for r in (rows or [])]


async def complete_exam_event(event_id: int, soz_no: int, score: Optional[str] = None) -> bool:
    await _exec(
        """UPDATE student_exam_calendar SET completed=TRUE, score=$3
           WHERE id=$1 AND soz_no=$2""",
        event_id, soz_no, score,
    )
    return True


# ── 5. ÇALIŞMA İSTATİSTİKLERİ ───────────────────────────────────────────

async def log_study_session(
    soz_no: int,
    minutes: int = 0,
    questions: int = 0,
    ders: Optional[str] = None,
    konu: Optional[str] = None,
    log_date: Optional[date] = None,
) -> dict:
    """Bugünün çalışma istatistiğine ekle (additive — UPDATE).

    ders/konu verilirse breakdown JSONB'ye eklenir.
    """
    log_date = log_date or date.today()
    # Mevcut kayıt var mı
    row = await _fetchrow(
        """SELECT id, total_minutes, questions_solved, ders_breakdown, konu_breakdown
           FROM student_study_stats
           WHERE soz_no=$1 AND log_date=$2""",
        soz_no, log_date,
    )

    if row:
        new_min = (row["total_minutes"] or 0) + max(0, minutes)
        new_q = (row["questions_solved"] or 0) + max(0, questions)
        # Breakdown güncelle
        ders_bd = row["ders_breakdown"] or {}
        konu_bd = row["konu_breakdown"] or {}
        if isinstance(ders_bd, str):
            try: ders_bd = json.loads(ders_bd)
            except: ders_bd = {}
        if isinstance(konu_bd, str):
            try: konu_bd = json.loads(konu_bd)
            except: konu_bd = {}
        if ders and minutes > 0:
            ders_bd[ders] = ders_bd.get(ders, 0) + minutes
        if konu and minutes > 0:
            konu_bd[konu] = konu_bd.get(konu, 0) + minutes
        await _exec(
            """UPDATE student_study_stats SET
               total_minutes=$1, questions_solved=$2,
               ders_breakdown=$3, konu_breakdown=$4, updated_at=NOW()
               WHERE id=$5""",
            new_min, new_q, json.dumps(ders_bd), json.dumps(konu_bd), row["id"],
        )
        return {"total_minutes": new_min, "questions_solved": new_q,
                "ders_breakdown": ders_bd, "konu_breakdown": konu_bd}
    else:
        ders_bd = {ders: minutes} if (ders and minutes > 0) else {}
        konu_bd = {konu: minutes} if (konu and minutes > 0) else {}
        await _exec(
            """INSERT INTO student_study_stats
               (soz_no, log_date, total_minutes, questions_solved, ders_breakdown, konu_breakdown)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            soz_no, log_date, max(0, minutes), max(0, questions),
            json.dumps(ders_bd), json.dumps(konu_bd),
        )
        return {"total_minutes": minutes, "questions_solved": questions,
                "ders_breakdown": ders_bd, "konu_breakdown": konu_bd}


async def get_today_stats(soz_no: int) -> dict:
    row = await _fetchrow(
        """SELECT total_minutes, questions_solved, ders_breakdown, konu_breakdown
           FROM student_study_stats WHERE soz_no=$1 AND log_date=CURRENT_DATE""",
        soz_no,
    )
    if not row:
        return {"total_minutes": 0, "questions_solved": 0, "ders_breakdown": {}, "konu_breakdown": {}}
    d = dict(row)
    if isinstance(d.get("ders_breakdown"), str):
        try: d["ders_breakdown"] = json.loads(d["ders_breakdown"])
        except: d["ders_breakdown"] = {}
    if isinstance(d.get("konu_breakdown"), str):
        try: d["konu_breakdown"] = json.loads(d["konu_breakdown"])
        except: d["konu_breakdown"] = {}
    return d


async def get_weekly_stats(soz_no: int, weeks: int = 1) -> dict:
    """Son N hafta toplam — analiz için."""
    rows = await _fetch(
        f"""SELECT log_date, total_minutes, questions_solved, ders_breakdown
            FROM student_study_stats
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(weeks * 7)} days'
            ORDER BY log_date""",
        soz_no,
    )
    daily = []
    total_min = 0
    total_q = 0
    ders_total = {}
    for r in (rows or []):
        d = dict(r)
        bd = d.get("ders_breakdown") or {}
        if isinstance(bd, str):
            try: bd = json.loads(bd)
            except: bd = {}
        for ders, mins in bd.items():
            ders_total[ders] = ders_total.get(ders, 0) + (mins or 0)
        total_min += d.get("total_minutes") or 0
        total_q += d.get("questions_solved") or 0
        daily.append({
            "date": str(d["log_date"]),
            "minutes": d.get("total_minutes") or 0,
            "questions": d.get("questions_solved") or 0,
        })
    return {
        "days": len(daily),
        "total_minutes": total_min,
        "total_questions": total_q,
        "avg_minutes_per_day": round(total_min / max(1, len(daily)), 1),
        "ders_breakdown": ders_total,
        "daily": daily,
    }


# ── 6. FİZİKSEL AKTİVİTE ────────────────────────────────────────────────

async def log_physical_activity(
    soz_no: int,
    activity_type: str = "egzersiz",
    duration_minutes: int = 0,
    intensity: str = "orta",
    notes: Optional[str] = None,
    log_date: Optional[date] = None,
) -> dict:
    log_date = log_date or date.today()
    if intensity not in ("düşük", "orta", "yüksek"):
        intensity = "orta"
    nid = await _fetchval(
        """INSERT INTO student_physical_activity
           (soz_no, log_date, activity_type, duration_minutes, intensity, notes)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
        soz_no, log_date, activity_type[:50], max(0, duration_minutes), intensity, notes,
    )
    return {"id": nid, "activity_type": activity_type, "duration_minutes": duration_minutes}


async def get_recent_activities(soz_no: int, days: int = 7) -> list[dict]:
    rows = await _fetch(
        f"""SELECT id, log_date, activity_type, duration_minutes, intensity, notes
            FROM student_physical_activity
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
            ORDER BY log_date DESC, created_at DESC""",
        soz_no,
    )
    return [dict(r) for r in (rows or [])]


# ── 7. BUGÜNKÜ NOTUM ────────────────────────────────────────────────────

async def add_daily_note(
    soz_no: int,
    note: str,
    mood: Optional[str] = None,
    log_date: Optional[date] = None,
) -> dict:
    log_date = log_date or date.today()
    if mood and mood not in ("verimli", "normal", "yorgun", "stresli", "motiveli"):
        mood = "normal"
    await _exec(
        """INSERT INTO student_daily_notes (soz_no, log_date, note, mood)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (soz_no, log_date) DO UPDATE SET
             note=EXCLUDED.note, mood=EXCLUDED.mood""",
        soz_no, log_date, note[:1000], mood,
    )
    return {"date": str(log_date), "note": note, "mood": mood}


async def get_recent_notes(soz_no: int, days: int = 7) -> list[dict]:
    rows = await _fetch(
        f"""SELECT log_date, note, mood, created_at
            FROM student_daily_notes
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
            ORDER BY log_date DESC""",
        soz_no,
    )
    return [dict(r) for r in (rows or [])]


# ── HIGH-LEVEL: get_summary (LLM için) ─────────────────────────────────────

async def get_summary(soz_no: int) -> dict:
    """Öğrencinin günlük takip özeti — bot ve dashboard için tek çağrı.

    Returns: {
      "today_program": [...],      # Bugünkü program
      "open_todos": [...],          # Açık to-do'lar
      "habits": [...],              # Aktif alışkanlıklar
      "upcoming_events": [...],     # Yaklaşan sınav/ödev (30g)
      "today_stats": {...},         # Bugünkü çalışma süre+soru
      "weekly_stats": {...},        # Son 7g toplam + ders breakdown
      "recent_activities": [...],   # Son 7g fiziksel aktivite
      "today_note": {...},          # Bugünkü not + mood
      "recent_notes": [...],        # Son 7g not
    }
    """
    program, todos, habits, events, today_stats, weekly, activities, notes = await asyncio.gather(
        get_daily_program(soz_no),
        get_todos(soz_no, only_open=True),
        get_habits(soz_no, active_only=True),
        get_upcoming_events(soz_no, days_ahead=30),
        get_today_stats(soz_no),
        get_weekly_stats(soz_no, weeks=1),
        get_recent_activities(soz_no, days=7),
        get_recent_notes(soz_no, days=7),
        return_exceptions=True,
    )

    # Exception'ları None ile değiştir
    def _safe(x, default):
        return default if isinstance(x, Exception) else x

    today_note = None
    notes_list = _safe(notes, [])
    if notes_list:
        for n in notes_list:
            if str(n.get("log_date")) == str(date.today()):
                today_note = n
                break

    return {
        "today_program": _safe(program, []),
        "open_todos": _safe(todos, []),
        "habits": _safe(habits, []),
        "upcoming_events": _safe(events, []),
        "today_stats": _safe(today_stats, {}),
        "weekly_stats": _safe(weekly, {}),
        "recent_activities": _safe(activities, []),
        "today_note": today_note,
        "recent_notes": notes_list[:7] if isinstance(notes_list, list) else [],
    }


async def analyze_study_pattern(soz_no: int, days: int = 30) -> dict:
    """30 günlük çalışma örüntü analizi — LLM için.

    Returns: {
      "total_days_logged": N,
      "total_minutes": int,
      "total_questions": int,
      "avg_minutes_per_active_day": float,
      "most_studied_subject": str,
      "most_studied_topic": str,
      "consistency_score": float,  # 0-1, kaç gün üst üste log gönderdi
      "weak_days": [str],          # haftanın hangi günleri az çalıştı
      "physical_activity_count": int,
      "mood_distribution": {...},
    }
    """
    rows = await _fetch(
        f"""SELECT log_date, total_minutes, questions_solved, ders_breakdown, konu_breakdown
            FROM student_study_stats
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
            ORDER BY log_date""",
        soz_no,
    )
    if not rows:
        return {"error": "no_data", "message": "Henüz çalışma kaydı yok."}

    total_min = sum(r["total_minutes"] or 0 for r in rows)
    total_q = sum(r["questions_solved"] or 0 for r in rows)
    active_days = len(rows)

    # En çok çalışılan ders/konu
    ders_total = {}
    konu_total = {}
    for r in rows:
        bd = r["ders_breakdown"] or {}
        kbd = r["konu_breakdown"] or {}
        if isinstance(bd, str):
            try: bd = json.loads(bd)
            except: bd = {}
        if isinstance(kbd, str):
            try: kbd = json.loads(kbd)
            except: kbd = {}
        for d, m in bd.items():
            ders_total[d] = ders_total.get(d, 0) + (m or 0)
        for k, m in kbd.items():
            konu_total[k] = konu_total.get(k, 0) + (m or 0)

    most_ders = max(ders_total.items(), key=lambda x: x[1])[0] if ders_total else None
    most_konu = max(konu_total.items(), key=lambda x: x[1])[0] if konu_total else None

    # Consistency: kaç gün üst üste log
    from datetime import date as _d
    today = _d.today()
    consistency = active_days / days  # basit oran

    # Haftanın hangi günleri zayıf?
    weekday_count = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    for r in rows:
        wd = r["log_date"].weekday()
        weekday_count[wd] += 1
    weekday_names = {0: "Pzt", 1: "Sal", 2: "Çar", 3: "Per", 4: "Cum", 5: "Cmt", 6: "Paz"}
    weak_days = [weekday_names[k] for k, v in weekday_count.items() if v < (days / 7) * 0.5]

    # Fiziksel aktivite + mood
    pa_count = await _fetchval(
        f"""SELECT COUNT(*) FROM student_physical_activity
            WHERE soz_no=$1 AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'""",
        soz_no,
    ) or 0

    mood_rows = await _fetch(
        f"""SELECT mood, COUNT(*) as cnt FROM student_daily_notes
            WHERE soz_no=$1 AND mood IS NOT NULL
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
            GROUP BY mood""",
        soz_no,
    )
    mood_dist = {r["mood"]: r["cnt"] for r in (mood_rows or [])}

    return {
        "period_days": days,
        "active_days_logged": active_days,
        "total_minutes": total_min,
        "total_hours": round(total_min / 60, 1),
        "total_questions": total_q,
        "avg_minutes_per_active_day": round(total_min / max(1, active_days), 1),
        "most_studied_subject": most_ders,
        "most_studied_topic": most_konu,
        "ders_breakdown_minutes": ders_total,
        "consistency_score": round(consistency, 2),
        "weak_weekdays": weak_days,
        "physical_activity_count": pa_count,
        "mood_distribution": mood_dist,
    }


if __name__ == "__main__":
    print("student_daily module loaded.")
