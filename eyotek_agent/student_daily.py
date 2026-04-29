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

def _parse_time(s) -> Optional[dtime]:
    """'14:00' veya '14:00:00' → datetime.time. None ise None."""
    if not s:
        return None
    if isinstance(s, dtime):
        return s
    s = str(s).strip()
    parts = s.split(':')
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        sec = int(parts[2]) if len(parts) > 2 else 0
        return dtime(hour=h, minute=m, second=sec)
    except Exception:
        return None


async def add_daily_program(
    soz_no: int,
    title: str,
    start_time: str,                # "09:00"
    end_time: Optional[str] = None,  # "10:00"
    plan_date: Optional[date] = None,
    ders: Optional[str] = None,
    konu: Optional[str] = None,
    notes: Optional[str] = None,
    is_test: bool = False,
) -> dict:
    """Günlük programa yeni blok ekle. is_test=True → admin test mode (bot context'e girmez)."""
    plan_date = plan_date or date.today()
    # Oturum 25.12 fix: asyncpg TIME tipi string kabul etmez, datetime.time gerekli
    start_t = _parse_time(start_time) or dtime(9, 0)
    end_t = _parse_time(end_time)
    nid = await _fetchval(
        """INSERT INTO student_daily_program
           (soz_no, plan_date, start_time, end_time, title, ders, konu, notes, is_test)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
        soz_no, plan_date, start_t, end_t,
        title[:200], ders, konu, notes, bool(is_test),
    )
    return {"id": nid, "title": title, "plan_date": str(plan_date), "is_test": is_test}


async def get_daily_program(soz_no: int, plan_date: Optional[date] = None,
                              include_test: bool = True) -> list[dict]:
    """Bir günün programı (default bugün).

    include_test=False: bot context icin — admin test kayitlari hariç tutulur.
    include_test=True (default): frontend dashboard — kendi test verisi de görünür.
    """
    plan_date = plan_date or date.today()
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT id, start_time::text, end_time::text, title, ders, konu, completed, notes,
                   COALESCE(is_test, FALSE) AS is_test
           FROM student_daily_program
           WHERE soz_no=$1 AND plan_date=$2{test_filter}
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
    is_test: bool = False,
) -> dict:
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"
    nid = await _fetchval(
        """INSERT INTO student_todo (soz_no, title, due_date, priority, is_test)
           VALUES ($1,$2,$3,$4,$5) RETURNING id""",
        soz_no, title[:200], due_date, priority, bool(is_test),
    )
    return {"id": nid, "title": title, "priority": priority, "is_test": is_test}


async def get_todos(soz_no: int, only_open: bool = True, include_test: bool = True) -> list[dict]:
    where = "soz_no=$1" + (" AND completed=FALSE" if only_open else "")
    if not include_test:
        where += " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT id, title, due_date, priority, completed, completed_at, created_at,
                   COALESCE(is_test, FALSE) AS is_test
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
    is_test: bool = False,
) -> dict:
    target_days = target_days or ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']
    nid = await _fetchval(
        """INSERT INTO student_habits (soz_no, habit_name, target_days, is_test)
           VALUES ($1,$2,$3,$4) RETURNING id""",
        soz_no, habit_name[:120], target_days, bool(is_test),
    )
    return {"id": nid, "habit_name": habit_name, "is_test": is_test}


async def delete_habit(habit_id: int, soz_no: int) -> bool:
    """Bir alışkanlığı sil (logları da siler — CASCADE)."""
    await _exec(
        "DELETE FROM student_habits WHERE id=$1 AND soz_no=$2",
        habit_id, soz_no,
    )
    return True


async def get_habits(soz_no: int, active_only: bool = True, include_test: bool = True) -> list[dict]:
    where = "soz_no=$1" + (" AND is_active=TRUE" if active_only else "")
    if not include_test:
        where += " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT id, habit_name, target_days, streak, longest_streak, created_at,
                   COALESCE(is_test, FALSE) AS is_test
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
    is_test: bool = False,
) -> dict:
    if event_type not in ("sinav", "odev", "etut", "rehberlik"):
        event_type = "sinav"
    # Oturum 25.12 fix: time parse
    et = _parse_time(event_time)
    nid = await _fetchval(
        """INSERT INTO student_exam_calendar
           (soz_no, title, event_type, event_date, event_time, ders, is_test)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
        soz_no, title[:200], event_type, event_date, et, ders, bool(is_test),
    )
    return {"id": nid, "title": title, "event_date": str(event_date), "is_test": is_test}


async def delete_event(event_id: int, soz_no: int) -> bool:
    """Sınav/etkinlik sil."""
    await _exec(
        "DELETE FROM student_exam_calendar WHERE id=$1 AND soz_no=$2",
        event_id, soz_no,
    )
    return True


async def get_upcoming_events(soz_no: int, days_ahead: int = 30,
                                include_test: bool = True) -> list[dict]:
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT id, title, event_type, event_date, event_time::text, ders, completed, score,
                   COALESCE(is_test, FALSE) AS is_test
            FROM student_exam_calendar
            WHERE soz_no=$1
              AND event_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '{int(days_ahead)} days'{test_filter}
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
    is_test: bool = False,
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
               (soz_no, log_date, total_minutes, questions_solved, ders_breakdown, konu_breakdown, is_test)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            soz_no, log_date, max(0, minutes), max(0, questions),
            json.dumps(ders_bd), json.dumps(konu_bd), bool(is_test),
        )
        return {"total_minutes": minutes, "questions_solved": questions,
                "ders_breakdown": ders_bd, "konu_breakdown": konu_bd}


async def get_today_stats(soz_no: int, include_test: bool = True) -> dict:
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    row = await _fetchrow(
        f"""SELECT total_minutes, questions_solved, ders_breakdown, konu_breakdown
           FROM student_study_stats WHERE soz_no=$1 AND log_date=CURRENT_DATE{test_filter}""",
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


async def get_weekly_stats(soz_no: int, weeks: int = 1, include_test: bool = True) -> dict:
    """Son N hafta toplam — analiz için."""
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT log_date, total_minutes, questions_solved, ders_breakdown
            FROM student_study_stats
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(weeks * 7)} days'{test_filter}
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
    is_test: bool = False,
) -> dict:
    log_date = log_date or date.today()
    if intensity not in ("düşük", "orta", "yüksek"):
        intensity = "orta"
    nid = await _fetchval(
        """INSERT INTO student_physical_activity
           (soz_no, log_date, activity_type, duration_minutes, intensity, notes, is_test)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id""",
        soz_no, log_date, activity_type[:50], max(0, duration_minutes), intensity, notes, bool(is_test),
    )
    return {"id": nid, "activity_type": activity_type, "duration_minutes": duration_minutes, "is_test": is_test}


async def get_recent_activities(soz_no: int, days: int = 7,
                                  include_test: bool = True) -> list[dict]:
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT id, log_date, activity_type, duration_minutes, intensity, notes,
                   COALESCE(is_test, FALSE) AS is_test
            FROM student_physical_activity
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'{test_filter}
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
    is_test: bool = False,
) -> dict:
    log_date = log_date or date.today()
    if mood and mood not in ("verimli", "normal", "yorgun", "stresli", "motiveli"):
        mood = "normal"
    await _exec(
        """INSERT INTO student_daily_notes (soz_no, log_date, note, mood, is_test)
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (soz_no, log_date) DO UPDATE SET
             note=EXCLUDED.note, mood=EXCLUDED.mood, is_test=EXCLUDED.is_test""",
        soz_no, log_date, note[:1000], mood, bool(is_test),
    )
    return {"date": str(log_date), "note": note, "mood": mood, "is_test": is_test}


async def delete_activity(activity_id: int, soz_no: int) -> bool:
    """Fiziksel aktivite kaydını sil."""
    await _exec(
        "DELETE FROM student_physical_activity WHERE id=$1 AND soz_no=$2",
        activity_id, soz_no,
    )
    return True


async def get_recent_notes(soz_no: int, days: int = 7,
                             include_test: bool = True) -> list[dict]:
    test_filter = "" if include_test else " AND COALESCE(is_test, FALSE) = FALSE"
    rows = await _fetch(
        f"""SELECT log_date, note, mood, created_at,
                   COALESCE(is_test, FALSE) AS is_test
            FROM student_daily_notes
            WHERE soz_no=$1
              AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'{test_filter}
            ORDER BY log_date DESC""",
        soz_no,
    )
    return [dict(r) for r in (rows or [])]


# ── HIGH-LEVEL: get_summary (LLM için) ─────────────────────────────────────

async def get_summary(soz_no: int, include_test: bool = True) -> dict:
    """Öğrencinin günlük takip özeti — bot ve dashboard için tek çağrı.

    include_test=True (default): admin test verisi DAHIL (frontend dashboard).
    include_test=False: bot context — admin test verileri HARIC (öğrenci konuşurken
        bot, admin'in test ettiği kayıtları "öğrencinin gerçek verisi" sanmaz).

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
        get_daily_program(soz_no, include_test=include_test),
        get_todos(soz_no, only_open=True, include_test=include_test),
        get_habits(soz_no, active_only=True, include_test=include_test),
        get_upcoming_events(soz_no, days_ahead=30, include_test=include_test),
        get_today_stats(soz_no, include_test=include_test),
        get_weekly_stats(soz_no, weeks=1, include_test=include_test),
        get_recent_activities(soz_no, days=7, include_test=include_test),
        get_recent_notes(soz_no, days=7, include_test=include_test),
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


async def get_analytics_data(soz_no: int, days: int = 30) -> dict:
    """Infografik dashboard için full analytics — tek çağrı.

    Oturum 25.14 — Frontend'in tüm chartlarını besleyen veri:
      • daily_timeline: 30 gün → her gün dakika+soru (line/heatmap)
      • ders_breakdown: ders bazlı toplam dakika + yüzde (doughnut)
      • top_konular: en çok çalışılan ilk 10 konu (bar)
      • mood_timeline: 14 gün → mood (emoji satırı)
      • totals: toplam saat/soru/ortalama
      • streak: ardışık çalışma günleri
      • activity_summary: fiziksel aktivite (gün, dk)
      • elo_top: top 10 mastery (knowledge_graph)
    """
    # Asyncio gather — paralel
    rows_stats, mood_rows, activities = await asyncio.gather(
        _fetch(
            f"""SELECT log_date, total_minutes, questions_solved,
                       ders_breakdown, konu_breakdown
                FROM student_study_stats
                WHERE soz_no=$1
                  AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
                ORDER BY log_date""",
            soz_no,
        ),
        _fetch(
            f"""SELECT log_date, mood, note FROM student_daily_notes
                WHERE soz_no=$1 AND mood IS NOT NULL
                  AND log_date >= CURRENT_DATE - INTERVAL '14 days'
                ORDER BY log_date""",
            soz_no,
        ),
        _fetch(
            f"""SELECT log_date, activity_type, duration_minutes
                FROM student_physical_activity
                WHERE soz_no=$1
                  AND log_date >= CURRENT_DATE - INTERVAL '{int(days)} days'
                ORDER BY log_date""",
            soz_no,
        ),
        return_exceptions=True,
    )

    if isinstance(rows_stats, Exception): rows_stats = []
    if isinstance(mood_rows, Exception): mood_rows = []
    if isinstance(activities, Exception): activities = []

    from datetime import date as _d, timedelta as _td

    # ── 1. Daily timeline (her gün için dolu/boş) ──
    today = _d.today()
    by_date = {}
    for r in (rows_stats or []):
        by_date[str(r["log_date"])] = {
            "minutes": r["total_minutes"] or 0,
            "questions": r["questions_solved"] or 0,
        }

    daily_timeline = []
    for i in range(days, -1, -1):
        d = today - _td(days=i)
        ds = str(d)
        rec = by_date.get(ds, {"minutes": 0, "questions": 0})
        daily_timeline.append({
            "date": ds,
            "weekday": d.weekday(),  # 0=Pzt, 6=Paz
            "minutes": rec["minutes"],
            "questions": rec["questions"],
        })

    # ── 2. Ders breakdown ──
    ders_total = {}
    konu_total = {}
    for r in (rows_stats or []):
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

    total_min_all = sum(ders_total.values())
    ders_breakdown = sorted(
        [{"name": k, "minutes": v, "percent": round(100 * v / max(1, total_min_all), 1)}
         for k, v in ders_total.items()],
        key=lambda x: -x["minutes"],
    )

    top_konular = sorted(
        [{"name": k, "minutes": v} for k, v in konu_total.items()],
        key=lambda x: -x["minutes"],
    )[:10]

    # ── 3. Mood timeline ──
    mood_timeline = []
    mood_dict = {}
    for r in (mood_rows or []):
        mood_dict[str(r["log_date"])] = r["mood"]
    for i in range(13, -1, -1):
        d = today - _td(days=i)
        mood_timeline.append({
            "date": str(d),
            "mood": mood_dict.get(str(d)),
        })

    # ── 4. Totals ──
    total_min = sum(r["total_minutes"] or 0 for r in (rows_stats or []))
    total_q = sum(r["questions_solved"] or 0 for r in (rows_stats or []))
    active_days = len([r for r in (rows_stats or []) if (r["total_minutes"] or 0) > 0])

    # ── 5. Streak (consecutive days) ──
    streak_current = 0
    for i in range(0, days):
        d = today - _td(days=i)
        rec = by_date.get(str(d), {"minutes": 0})
        if rec["minutes"] > 0:
            streak_current += 1
        else:
            if i == 0:
                continue  # bugün boş ise dünden sayma başlat
            break
    longest_streak = 0
    cur = 0
    for entry in daily_timeline:
        if entry["minutes"] > 0:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    # ── 6. Activity summary ──
    pa_total_min = sum(a["duration_minutes"] or 0 for a in (activities or []))
    pa_days = len(set(str(a["log_date"]) for a in (activities or [])))

    # ── 7. ELO top (knowledge_graph entegrasyon) ──
    elo_top = []
    try:
        elo_rows = await _fetch(
            """SELECT ders, konu, rating, games_played
               FROM student_topic_elo WHERE soz_no=$1
               ORDER BY rating DESC LIMIT 10""",
            soz_no,
        )
        elo_top = [dict(r) for r in (elo_rows or [])]
    except Exception:
        pass

    return {
        "period_days": days,
        "totals": {
            "total_minutes": total_min,
            "total_hours": round(total_min / 60, 1),
            "total_questions": total_q,
            "active_days": active_days,
            "avg_minutes_per_active_day": round(total_min / max(1, active_days), 1),
            "current_streak": streak_current,
            "longest_streak": longest_streak,
        },
        "daily_timeline": daily_timeline,
        "ders_breakdown": ders_breakdown,
        "top_konular": top_konular,
        "mood_timeline": mood_timeline,
        "physical_activity": {
            "total_minutes": pa_total_min,
            "days_active": pa_days,
        },
        "elo_top": elo_top,
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
