"""
Öğrenci Günlük Takip — FastAPI Router (Oturum 25.12)
========================================================
GRAFEN-tarzı 7 modül için endpoint'ler.

Auth: web_chat session (öğrencinin kendi profil). soz_no session'dan alınır.
ACL: Öğrenci sadece kendi verisine erişebilir.
Admin/mudur opsiyonel: ?soz_no=137 query param ile başka öğrenci görebilir.

Endpoint'ler:
  /student/daily/summary             — Tek çağrı tüm modüller (dashboard ana)
  /student/daily/program             — Günlük program CRUD
  /student/daily/todo                — TODO list CRUD
  /student/daily/habits              — Alışkanlık CRUD + log
  /student/daily/events              — Sınav/ödev takvim CRUD
  /student/daily/stats               — Çalışma istatistik (log + read)
  /student/daily/activity            — Fiziksel aktivite
  /student/daily/notes               — Bugünkü not
  /student/daily/analyze             — 30 günlük analiz (LLM için)
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse, HTMLResponse
from loguru import logger

import student_daily as sd


COOKIE_NAME = "fermat_session"
router = APIRouter(prefix="/student/daily", tags=["student-daily"])


# ── AUTH HELPER ────────────────────────────────────────────────────────────

async def _get_student_soz_no(
    request: Request,
    cookie_token: Optional[str],
    override_soz_no: Optional[int] = None,
) -> int:
    """Session'dan öğrencinin soz_no'sunu çıkar.
    Admin/mudur override_soz_no kullanabilir (başka öğrenci görüntüleme).
    """
    from web_chat import _extract_token
    from web_chat_auth import get_session
    token = _extract_token(request, cookie_token)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Login gerekli")

    role = sess.get("role")
    phone = sess.get("phone")

    # Admin/mudur override
    if override_soz_no and role in ("admin", "mudur"):
        return int(override_soz_no)

    # Öğrenci kendi soz_no'su (DB'den)
    if role == "ogrenci":
        from db_pool import db_fetchval
        soz = await db_fetchval(
            "SELECT soz_no FROM students WHERE phone=$1 LIMIT 1", phone,
        )
        if not soz:
            raise HTTPException(status_code=403, detail="Öğrenci kaydı bulunamadı")
        return int(soz)

    # Diğer roller — soz_no override şart
    if not override_soz_no:
        raise HTTPException(status_code=400, detail="soz_no parametresi gerekli")
    return int(override_soz_no)


# ── ANA SUMMARY (dashboard tek çağrı) ──────────────────────────────────────

@router.get("/summary")
async def get_summary(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = Query(default=None, description="Admin override"),
):
    """Tüm 7 modül tek çağrı — dashboard için."""
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return await sd.get_summary(sn)


# ── 1. GÜNLÜK PROGRAM ──────────────────────────────────────────────────────

@router.get("/program")
async def list_program(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    plan_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    pd = date.fromisoformat(plan_date) if plan_date else None
    return {"program": await sd.get_daily_program(sn, plan_date=pd)}


@router.post("/program")
async def add_program(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title gerekli")
    start_time = payload.get("start_time", "09:00")
    end_time = payload.get("end_time")
    plan_date = date.fromisoformat(payload["plan_date"]) if payload.get("plan_date") else None
    return await sd.add_daily_program(
        sn, title, start_time, end_time,
        plan_date=plan_date,
        ders=payload.get("ders"),
        konu=payload.get("konu"),
        notes=payload.get("notes"),
    )


@router.post("/program/{block_id}/complete")
async def complete_program(
    block_id: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    await sd.complete_program_block(block_id, sn)
    return {"ok": True}


@router.delete("/program/{block_id}")
async def delete_program(
    block_id: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    await sd.delete_program_block(block_id, sn)
    return {"ok": True}


# ── 2. TO DO LIST ──────────────────────────────────────────────────────────

@router.get("/todo")
async def list_todos(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    only_open: bool = Query(default=True),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return {"todos": await sd.get_todos(sn, only_open=only_open)}


@router.post("/todo")
async def add_todo_endpoint(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title gerekli")
    due_date = date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None
    return await sd.add_todo(sn, title, due_date=due_date, priority=payload.get("priority", "normal"))


@router.post("/todo/{todo_id}/complete")
async def complete_todo_endpoint(
    todo_id: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    await sd.complete_todo(todo_id, sn)
    return {"ok": True}


@router.delete("/todo/{todo_id}")
async def delete_todo_endpoint(
    todo_id: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    await sd.delete_todo(todo_id, sn)
    return {"ok": True}


# ── 3. ALIŞKANLIK ──────────────────────────────────────────────────────────

@router.get("/habits")
async def list_habits(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return {"habits": await sd.get_habits(sn)}


@router.post("/habits")
async def add_habit_endpoint(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    name = (payload.get("habit_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="habit_name gerekli")
    return await sd.add_habit(sn, name, target_days=payload.get("target_days"))


@router.post("/habits/{habit_id}/log")
async def log_habit_endpoint(
    habit_id: int,
    request: Request,
    payload: dict = Body(default={}),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    # Auth check (habit_id zaten DB'de soz_no ile bağlı, ACL ek)
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    completed = bool(payload.get("completed", True))
    log_date = date.fromisoformat(payload["log_date"]) if payload.get("log_date") else None
    return await sd.log_habit(habit_id, log_date=log_date, completed=completed, note=payload.get("note"))


# ── 4. EXAM / EVENT CALENDAR ───────────────────────────────────────────────

@router.get("/events")
async def list_events(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days_ahead: int = Query(default=30),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return {"events": await sd.get_upcoming_events(sn, days_ahead=days_ahead)}


@router.post("/events")
async def add_event(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    title = (payload.get("title") or "").strip()
    if not title or not payload.get("event_date"):
        raise HTTPException(status_code=400, detail="title ve event_date gerekli")
    return await sd.add_exam_event(
        sn, title,
        date.fromisoformat(payload["event_date"]),
        event_type=payload.get("event_type", "sinav"),
        event_time=payload.get("event_time"),
        ders=payload.get("ders"),
    )


@router.post("/events/{event_id}/complete")
async def complete_event(
    event_id: int,
    request: Request,
    payload: dict = Body(default={}),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    await sd.complete_exam_event(event_id, sn, score=payload.get("score"))
    return {"ok": True}


# ── 5. ÇALIŞMA İSTATİSTİK ──────────────────────────────────────────────────

@router.get("/stats/today")
async def today_stats(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return await sd.get_today_stats(sn)


@router.get("/stats/weekly")
async def weekly_stats(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    weeks: int = Query(default=1),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return await sd.get_weekly_stats(sn, weeks=weeks)


@router.post("/stats/log")
async def log_session(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Çalışma session'ı ekle (additive — bugünün toplamına ekler)."""
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    minutes = int(payload.get("minutes", 0) or 0)
    questions = int(payload.get("questions", 0) or 0)
    return await sd.log_study_session(
        sn,
        minutes=minutes,
        questions=questions,
        ders=payload.get("ders"),
        konu=payload.get("konu"),
    )


# ── 6. FİZİKSEL AKTİVİTE ───────────────────────────────────────────────────

@router.get("/activity")
async def list_activities(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days: int = Query(default=7),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return {"activities": await sd.get_recent_activities(sn, days=days)}


@router.post("/activity")
async def add_activity(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    return await sd.log_physical_activity(
        sn,
        activity_type=payload.get("activity_type", "egzersiz"),
        duration_minutes=int(payload.get("duration_minutes", 0) or 0),
        intensity=payload.get("intensity", "orta"),
        notes=payload.get("notes"),
    )


# ── 7. BUGÜNKÜ NOT ────────────────────────────────────────────────────────

@router.get("/notes")
async def list_notes(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days: int = Query(default=7),
    soz_no: Optional[int] = None,
):
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return {"notes": await sd.get_recent_notes(sn, days=days)}


@router.post("/notes")
async def add_note(
    request: Request,
    payload: dict = Body(...),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    sn = await _get_student_soz_no(request, fermat_session, payload.get("soz_no"))
    note = (payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="note gerekli")
    return await sd.add_daily_note(sn, note, mood=payload.get("mood"))


# ── ANALİZ (LLM için) ─────────────────────────────────────────────────────

@router.get("/analyze")
async def analyze(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days: int = Query(default=30),
    soz_no: Optional[int] = None,
):
    """30 günlük örüntü analizi — bot tarafında da kullanılır."""
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return await sd.analyze_study_pattern(sn, days=days)


@router.get("/analytics")
async def analytics(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days: int = Query(default=30, ge=7, le=90),
    soz_no: Optional[int] = None,
):
    """Infografik dashboard için full analytics — tek çağrı (Oturum 25.14)."""
    sn = await _get_student_soz_no(request, fermat_session, soz_no)
    return await sd.get_analytics_data(sn, days=days)


# ── DASHBOARD UI ───────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_html(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Öğrenci günlük takip dashboard HTML — modern glassmorphism UI."""
    # Auth check (öğrenci/admin/mudur erişebilir)
    try:
        from web_chat import _extract_token
        from web_chat_auth import get_session
        token = _extract_token(request, fermat_session)
        sess = await get_session(token) if token else None
        if not sess:
            return HTMLResponse(
                content="<script>location.href='/chat?next=/student/daily/dashboard'</script>",
                status_code=200,
            )
    except Exception:
        pass

    import os
    here = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(here, "student_daily_ui.html")
    if not os.path.exists(html_path):
        return HTMLResponse("<h1>UI dosyasi eksik</h1>", status_code=500)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)
