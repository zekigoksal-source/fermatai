"""
Dashboard API (Oturum 25.9)
============================
Web admin dashboard endpoints — FastAPI router.

Endpoint'ler:
  GET  /admin/dashboard               → HTML dashboard (HTMX + Chart.js)
  GET  /admin/api/notifications       → JSON liste
  POST /admin/api/notifications/{id}/read
  POST /admin/api/notifications/{id}/dismiss
  GET  /admin/api/routing-stats       → Routing dağılımı (24h)
  GET  /admin/api/usage-summary       → Kullanım istatistik (24h, 7d, 30d)
  GET  /admin/api/cohort-analysis     → Devre/sınıf karşılaştırma
  GET  /admin/api/teacher-effectiveness → Öğretmen verimlilik
  GET  /admin/api/token-budget        → Per-user token maliyet
  GET  /admin/api/atlas-suggestions   → Bekleyen Atlas-2 önerileri
  POST /admin/api/atlas-suggestions/{id}/approve
  POST /admin/api/atlas-suggestions/{id}/reject
  POST /admin/api/atlas-suggestions/{id}/apply
  GET  /admin/api/student/{soz_no}/prediction
  GET  /admin/api/student/{soz_no}/knowledge-graph
  GET  /admin/api/student/{soz_no}/adaptive-summary

Auth: web_chat _require_admin
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
from loguru import logger

from db_pool import db_fetch, db_fetchrow, db_fetchval, db_execute


# Cookie name'i web_chat ile uyumlu (fermat_session)
COOKIE_NAME = "fermat_session"

router = APIRouter(prefix="/admin", tags=["dashboard"])


# ── AUTH GUARD ─────────────────────────────────────────────────────────────

async def _require_admin_session(
    request: Request,
    cookie_token: Optional[str],
) -> dict:
    """web_chat session'i ile auth (cookie veya Bearer).
    Admin/mudur degilse 403."""
    from web_chat import _extract_token, get_session, _require_admin
    token = _extract_token(request, cookie_token)
    sess = await get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Login gerekli")
    _require_admin(sess)
    return sess


# ── NOTIFICATIONS ──────────────────────────────────────────────────────────

@router.get("/api/notifications")
async def get_notifications(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    limit: int = 50,
    only_unread: bool = False,
):
    await _require_admin_session(request, fermat_session)
    where = "WHERE is_dismissed=FALSE"
    if only_unread:
        where += " AND is_read=FALSE"
    rows = await db_fetch(
        f"""SELECT id, severity, category, title, body, related_soz_no, related_phone,
                   is_read, created_at, metadata
            FROM notifications {where}
            ORDER BY (severity='critical') DESC, (severity='warning') DESC,
                     is_read ASC, created_at DESC
            LIMIT $1""",
        limit,
    )
    items = []
    for r in (rows or []):
        items.append({
            "id": r['id'],
            "severity": r['severity'],
            "category": r['category'],
            "title": r['title'],
            "body": r['body'],
            "related_soz_no": r['related_soz_no'],
            "related_phone": r['related_phone'],
            "is_read": r['is_read'],
            "created_at": r['created_at'].isoformat() if r['created_at'] else None,
            "metadata": r['metadata'],
        })
    counts = await db_fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE is_read=FALSE AND is_dismissed=FALSE) as unread,
             COUNT(*) FILTER (WHERE severity='critical' AND is_dismissed=FALSE) as critical,
             COUNT(*) FILTER (WHERE is_dismissed=FALSE) as total
           FROM notifications""",
    )
    return {"items": items, "counts": dict(counts) if counts else {}}


@router.post("/api/notifications/{nid}/read")
async def mark_notification_read(
    nid: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    await db_execute(
        "UPDATE notifications SET is_read=TRUE, read_at=NOW() WHERE id=$1",
        nid,
    )
    return {"ok": True}


@router.post("/api/notifications/{nid}/dismiss")
async def dismiss_notification(
    nid: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    await db_execute(
        "UPDATE notifications SET is_dismissed=TRUE, dismissed_at=NOW() WHERE id=$1",
        nid,
    )
    return {"ok": True}


# ── ROUTING STATS ──────────────────────────────────────────────────────────

@router.get("/api/routing-stats")
async def routing_stats(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    hours: int = 24,
):
    await _require_admin_session(request, fermat_session)
    rows = await db_fetch(
        f"""SELECT response_source, COUNT(*) as cnt, AVG(response_ms)::INT as avg_ms
            FROM routing_stats
            WHERE created_at >= NOW() - INTERVAL '{int(hours)} hours'
            GROUP BY response_source ORDER BY cnt DESC""",
    )
    total = sum(r['cnt'] for r in (rows or []))
    items = []
    for r in (rows or []):
        items.append({
            "source": r['response_source'],
            "count": r['cnt'],
            "pct": round(100 * r['cnt'] / total, 1) if total else 0,
            "avg_ms": r['avg_ms'],
        })
    return {"hours": hours, "total": total, "distribution": items}


# ── USAGE SUMMARY ──────────────────────────────────────────────────────────

@router.get("/api/usage-summary")
async def usage_summary(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    out = {}
    for label, hours in [("24h", 24), ("7d", 168), ("30d", 720)]:
        row = await db_fetchrow(
            f"""SELECT COUNT(DISTINCT phone) as users, COUNT(*) as msgs,
                       AVG(response_ms)::INT as avg_ms
                FROM usage_log
                WHERE created_at >= NOW() - INTERVAL '{int(hours)} hours'""",
        )
        out[label] = dict(row) if row else {}
    return out


# ── COHORT / CLASS ANALYSIS ────────────────────────────────────────────────

@router.get("/api/cohort-analysis")
async def cohort_analysis(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    # Sınıf bazında ortalama performans
    rows = await db_fetch(
        """SELECT s.class_name,
                  COUNT(DISTINCT s.soz_no) as ogr_sayisi,
                  AVG(se.toplam) FILTER (WHERE se.exam_type='TYT' AND se.status='valid') as tyt_ort,
                  AVG(se.toplam) FILTER (WHERE se.exam_type='AYT' AND se.status='valid') as ayt_ort
           FROM students s
           LEFT JOIN student_exams se ON se.soz_no = s.soz_no
           WHERE s.status='active'
             AND s.class_name NOT ILIKE '%mezun%'
             AND s.class_name NOT ILIKE '%mez %'
           GROUP BY s.class_name
           HAVING COUNT(DISTINCT s.soz_no) >= 2
           ORDER BY tyt_ort DESC NULLS LAST""",
    )
    return {"cohorts": [dict(r) for r in (rows or [])]}


# ── TEACHER EFFECTIVENESS ──────────────────────────────────────────────────

@router.get("/api/teacher-effectiveness")
async def teacher_effectiveness(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    rows = await db_fetch(
        """SELECT ogretmen, COUNT(*) as etut_sayisi,
                  COUNT(DISTINCT konu) as farkli_konu,
                  COUNT(DISTINCT ogrenci_sayisi) as farkli_ogr_grup,
                  AVG(sure)::INT as ort_sure_dk
           FROM etut_history
           WHERE tarih >= CURRENT_DATE - INTERVAL '30 days'
           GROUP BY ogretmen
           HAVING COUNT(*) >= 3
           ORDER BY etut_sayisi DESC LIMIT 30""",
    )
    return {"period": "30d", "teachers": [dict(r) for r in (rows or [])]}


# ── TOKEN BUDGET (T2 — placeholder, basit yaklaşım) ─────────────────────────

@router.get("/api/token-budget")
async def token_budget(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    days: int = 7,
):
    await _require_admin_session(request, fermat_session)
    # usage_log'dan source başına maliyet tahmini
    # Maliyet katsayıları (rough):
    #   fast_response: $0
    #   ollama: $0
    #   groq: $0.0001 per message (avg 200 tok)
    #   claude: $0.003 per message (avg 500 tok)
    rows = await db_fetch(
        f"""SELECT phone, full_name, role,
                   COUNT(*) FILTER (WHERE response_source='claude') as claude_cnt,
                   COUNT(*) FILTER (WHERE response_source='groq') as groq_cnt,
                   COUNT(*) FILTER (WHERE response_source='fast_response') as fast_cnt,
                   COUNT(*) as total_cnt
            FROM usage_log
            WHERE created_at >= NOW() - INTERVAL '{int(days)} days'
            GROUP BY phone, full_name, role
            ORDER BY claude_cnt DESC LIMIT 50""",
    )
    items = []
    for r in (rows or []):
        cost_usd = (r['claude_cnt'] or 0) * 0.003 + (r['groq_cnt'] or 0) * 0.0001
        items.append({
            "phone": r['phone'],
            "full_name": r['full_name'],
            "role": r['role'],
            "claude": r['claude_cnt'],
            "groq": r['groq_cnt'],
            "fast": r['fast_cnt'],
            "total": r['total_cnt'],
            "cost_usd": round(cost_usd, 4),
        })
    total_cost = sum(i['cost_usd'] for i in items)
    return {"days": days, "users": items, "total_cost_usd": round(total_cost, 2)}


# ── ATLAS-2 PROMPT SUGGESTIONS ─────────────────────────────────────────────

@router.get("/api/atlas-suggestions")
async def list_suggestions(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    from prompt_optimizer import get_pending_suggestions
    items = await get_pending_suggestions(limit=20)
    return {"suggestions": items}


@router.post("/api/atlas-suggestions/{sid}/approve")
async def approve_sug(
    sid: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    from prompt_optimizer import approve_suggestion
    return await approve_suggestion(sid, reviewer="neo")


@router.post("/api/atlas-suggestions/{sid}/reject")
async def reject_sug(
    sid: int,
    request: Request,
    payload: dict = Body(default={}),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    from prompt_optimizer import reject_suggestion
    note = (payload or {}).get("note", "")
    return await reject_suggestion(sid, reviewer="neo", note=note)


@router.post("/api/atlas-suggestions/{sid}/apply")
async def apply_sug(
    sid: int,
    request: Request,
    payload: dict = Body(default={}),
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    from prompt_optimizer import apply_suggestion
    dry = bool((payload or {}).get("dry_run", True))
    return await apply_suggestion(sid, dry_run=dry)


# ── STUDENT ENDPOINTS ──────────────────────────────────────────────────────

@router.get("/api/student/{soz_no}/prediction")
async def student_prediction(
    soz_no: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    fresh: bool = False,
):
    await _require_admin_session(request, fermat_session)
    from predictive_model import predict_student, get_latest_prediction
    if fresh:
        return await predict_student(soz_no)
    cached = await get_latest_prediction(soz_no)
    if cached:
        return cached
    return await predict_student(soz_no)


@router.get("/api/student/{soz_no}/knowledge-graph")
async def student_kg(
    soz_no: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    seviye: Optional[str] = None,
):
    await _require_admin_session(request, fermat_session)
    from knowledge_graph import get_student_graph, update_student_mastery_from_elo
    # Önce ELO'dan mastery güncelle (hızlı)
    try:
        await update_student_mastery_from_elo(soz_no)
    except Exception:
        pass
    return await get_student_graph(soz_no, seviye=seviye)


@router.get("/api/student/{soz_no}/adaptive-summary")
async def student_adaptive(
    soz_no: int,
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    await _require_admin_session(request, fermat_session)
    from adaptive_engine import get_adaptive_summary
    return await get_adaptive_summary(soz_no)


# ── DASHBOARD HTML ─────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_html(
    request: Request,
    fermat_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
):
    """Ana dashboard sayfası — HTMX + Chart.js."""
    try:
        await _require_admin_session(request, fermat_session)
    except HTTPException:
        # Login redirect
        return HTMLResponse(
            content="<script>location.href='/chat?next=/admin/dashboard'</script>",
            status_code=200,
        )

    import os
    here = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(here, "dashboard_ui.html")
    if not os.path.exists(html_path):
        return HTMLResponse(
            "<h1>Dashboard UI eksik</h1><p>dashboard_ui.html bulunamadi</p>",
            status_code=500,
        )
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)
