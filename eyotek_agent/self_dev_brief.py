"""
Self-Dev Brief Writer (Oturum 25.29 — Evre 1)
==============================================

Konusma → Claude Code-ready brief.

Workflow:
  Neo: "brief yaz" / "brief olustur" / "self dev brief"
   → write_brief(phone, last_n_messages=20)
   → DB'ye kaydet (self_dev_briefs)
   → Neo'ya WP'da: "Brief #N hazır, 3 dosya, risk: orta"

Brief icerigi:
  - title (kısa baslık)
  - problem_summary (1-2 cümle)
  - files_touched (read_file ile DOĞRULANMIŞ yollar)
  - proposed_diff (psödo-diff veya unified diff format)
  - risk_level (low/medium/high — heuristic)

Onemli: Brief HAYAL üretemez. files_touched read_file ile gerçek
dosyalar uzerinde dogrulanir. Bot "şu dosya yok" derse o dosya
listeye GIRMEZ.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from typing import Optional

from loguru import logger


# Risk heuristikleri
HIGH_RISK_FILES = [
    "system_prompts.py",
    "whatsapp_bridge.py",
    "tool_definitions.py",
    "fermat_core_agent.py",
    "role_access.py",
    "_security",
    ".env",
    ".sql",
    "schema.sql",
    "migrations/",
    ".service",
    ".timer",
]
MEDIUM_RISK_FILES = [
    "fast_responses.py",
    "conversation_memory.py",
    "context_engine.py",
    "student_scenarios.py",
    "intent_parser.py",
    "llm_router.py",
]
# Geri kalan = low risk


def _assess_risk(files: list[str]) -> str:
    """Files listesinden risk seviyesi cikar."""
    if not files:
        return "low"
    files_str = " | ".join(files).lower()
    for hr in HIGH_RISK_FILES:
        if hr.lower() in files_str:
            return "high"
    for mr in MEDIUM_RISK_FILES:
        if mr.lower() in files_str:
            return "medium"
    return "low"


async def _verify_files_exist(files: list[str]) -> tuple[list[str], list[str]]:
    """files listesini self_dev_tools.read_file ile doğrula. (existing, missing)."""
    from self_dev_tools import _is_allowed_path
    import os
    existing = []
    missing = []
    for f in files or []:
        # Mutlak veya repo-relative
        candidates = [f]
        if not os.path.isabs(f):
            candidates.append(os.path.join("/opt/fermatai", f))
            candidates.append(os.path.join("/opt/fermatai/eyotek_agent", f))
        found = False
        for c in candidates:
            ok, _ = _is_allowed_path(c)
            if ok and os.path.exists(c):
                existing.append(c)
                found = True
                break
        if not found:
            missing.append(f)
    return existing, missing


async def write_brief(
    triggered_by: str,
    last_n: int = 30,
    extra_hint: str = "",
) -> dict:
    """Son N admin (Neo) mesajini analiz edip brief üret.

    Args:
        triggered_by: Tetikleyen telefon (admin)
        last_n: Son kaç mesajı analiz et
        extra_hint: Neo ekstra ipucu verirse ('mehmet bug hakkinda')

    Returns:
        {brief_id, title, files, risk, body, status='draft'}
    """
    # Pipeline aktif mi
    from self_dev_tools import _is_pipeline_active, _audit
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali. Neo 'self dev ac' yazabilir."}

    # Son N admin konusmasi
    from db_pool import db_fetch
    rows = await db_fetch(
        """SELECT message_role, content, created_at
           FROM agent_conversations
           WHERE phone = $1
             AND created_at > NOW() - INTERVAL '24 hours'
           ORDER BY created_at DESC
           LIMIT $2""",
        triggered_by, int(last_n),
    )
    if not rows:
        return {"error": "Son 24 saatte konuşma bulunamadı"}

    # Kronolojik sirala
    msgs = list(reversed([dict(r) for r in rows]))
    transcript = "\n".join(
        f"[{m['message_role']}] {(m['content'] or '')[:1500]}"
        for m in msgs
    )

    # LLM cagri — Claude (kalite + dosya analizi gerek)
    from llm_router import LLMRouter
    router = LLMRouter()

    sys_prompt = """Sen FermatAI sistemi icin self-dev brief writer'sin.

GORE V:
Konusmadan KOD DEGISIKLIGI ONERISI cikar. Output sadece JSON formatinda.

JSON SCHEMA:
{
  "title": "kisa baslik (max 60 char) — ne yapilacak",
  "problem_summary": "1-2 cumle: sorun nedir, kok neden ne",
  "files_touched": ["eyotek_agent/dosya1.py", "eyotek_agent/dosya2.py"],
  "proposed_changes": [
    {
      "file": "eyotek_agent/dosya.py",
      "where": "fonksiyon X / satir Y / class Z",
      "change_type": "add|modify|remove",
      "description": "ne degisecek (1-2 cumle)",
      "pseudo_diff": "ESKI: ... \\nYENI: ... (kisa, anlasilir)"
    }
  ],
  "test_plan": "nasil test edilecek (1-3 cumle)",
  "rollback_note": "geri almak gerekirse ne yapilir"
}

KURALLAR:
- Files SADECE tahmin et, UYDURMA. Bilmediginsen bos liste don.
- Proposed_diff PSÖDO format, gercek unified diff degil — Neo Claude Code ile uygulayacak.
- Eger konusmada NET bir kod degisikligi yoksa → {"title": "Brief üretilemedi", "files_touched": [], "proposed_changes": []}
"""

    user_prompt = f"""KONUSMA TRANSKRIPTI (son {len(msgs)} mesaj):

{transcript[:8000]}

EKSTRA IPUCU: {extra_hint or '(yok)'}

Yukaridaki konusmadan brief üret. SADECE JSON yaz, baska hicbir sey yazma."""

    try:
        # Claude API direkt — chat_cloud (sync), async context'te to_thread ile
        # Brief üretimi tool gerektirmez, basit text-out
        import asyncio as _asyncio
        resp = await _asyncio.to_thread(
            router.chat_cloud,
            [{"role": "user", "content": user_prompt}],
            sys_prompt,
            None,
            "",
        )
        raw = "\n".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception as e:
        await _audit(triggered_by, "write_brief", {"last_n": last_n}, False, error=str(e))
        return {"error": f"LLM hatasi: {str(e)[:200]}"}

    # JSON parse
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"error": "Brief LLM JSON döndüremedi", "raw_preview": raw[:300]}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse hatasi: {e}", "raw_preview": raw[:300]}

    title = (data.get("title") or "Untitled brief")[:200]
    summary = (data.get("problem_summary") or "")[:1000]
    files_proposed = data.get("files_touched") or []
    changes = data.get("proposed_changes") or []
    test_plan = data.get("test_plan") or ""
    rollback = data.get("rollback_note") or ""

    # Files dogrulama
    existing, missing = await _verify_files_exist(files_proposed)

    # Risk
    risk = _assess_risk(existing or files_proposed)

    # Diff metni — psödo-diff'leri birleştir
    diff_parts = []
    for ch in changes:
        diff_parts.append(
            f"--- {ch.get('file', '?')}\n"
            f"## {ch.get('where', '?')} ({ch.get('change_type', 'modify')})\n"
            f"# {ch.get('description', '')}\n"
            f"{ch.get('pseudo_diff', '')}"
        )
    if test_plan:
        diff_parts.append(f"\n## TEST PLAN\n{test_plan}")
    if rollback:
        diff_parts.append(f"\n## ROLLBACK\n{rollback}")
    if missing:
        diff_parts.append(f"\n## ⚠️ DOĞRULANMAYAN dosyalar (hayal olabilir):\n  - " + "\n  - ".join(missing))
    diff_text = "\n\n".join(diff_parts)[:30000]

    # DB'ye kaydet
    from db_pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        brief_id = await conn.fetchval(
            """INSERT INTO self_dev_briefs
               (triggered_by, title, problem_summary, files_touched,
                proposed_diff, risk_level, status, conversation_id)
               VALUES ($1,$2,$3,$4,$5,$6,'draft',$7)
               RETURNING id""",
            triggered_by, title, summary,
            existing or files_proposed,
            diff_text, risk,
            f"conv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        )

    await _audit(triggered_by, "write_brief",
                 {"last_n": last_n, "brief_id": brief_id}, True,
                 bytes_read=len(diff_text))

    return {
        "ok": True,
        "brief_id": brief_id,
        "title": title,
        "files_verified": existing,
        "files_unverified": missing,
        "risk": risk,
        "summary": summary,
        "diff_preview": diff_text[:1500],
        "full_diff_length": len(diff_text),
    }


async def list_briefs(triggered_by: str = "", status: str = "",
                      limit: int = 10) -> list[dict]:
    """Brief geçmişi (admin için)."""
    from db_pool import db_fetch
    where = ["1=1"]
    params: list = [int(limit)]
    pn = 2
    if triggered_by:
        where.append(f"triggered_by = ${pn}")
        params.append(triggered_by); pn += 1
    if status:
        where.append(f"status = ${pn}")
        params.append(status); pn += 1
    sql = f"""SELECT id, created_at, title, risk_level, status,
                     array_length(files_touched, 1) AS n_files
               FROM self_dev_briefs
               WHERE {' AND '.join(where)}
               ORDER BY created_at DESC
               LIMIT $1"""
    try:
        rows = await db_fetch(sql, *params)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"[BRIEF] list fail: {e}")
        return []


async def get_brief(brief_id: int) -> Optional[dict]:
    """Tek brief detayı."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT id, created_at, triggered_by, title, problem_summary,
                      files_touched, proposed_diff, risk_level, status,
                      applied_commit, applied_at, notes
               FROM self_dev_briefs WHERE id = $1""",
            int(brief_id),
        )
        return dict(row) if row else None
    except Exception:
        return None


async def update_brief_status(brief_id: int, status: str,
                              applied_commit: str = "",
                              notes: str = "") -> bool:
    """draft → reviewed/applied/discarded."""
    if status not in ("draft", "reviewed", "applied", "discarded"):
        return False
    from db_pool import get_pool
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE self_dev_briefs
                   SET status = $2,
                       applied_commit = COALESCE(NULLIF($3,''), applied_commit),
                       applied_at = CASE WHEN $2 = 'applied' THEN NOW() ELSE applied_at END,
                       notes = COALESCE(NULLIF($4,''), notes)
                   WHERE id = $1""",
                int(brief_id), status, applied_commit, notes,
            )
        return True
    except Exception:
        return False


# ─── WhatsApp formatlı çıktı ──────────────────────────────────────────────

def format_brief_for_wp(brief: dict) -> str:
    """Brief'i WhatsApp markdown formatında özetle."""
    if not brief:
        return "_Brief bulunamadı._"
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(brief.get("risk_level", ""), "⚪")
    files = brief.get("files_touched") or []
    lines = [
        f"*📋 Brief #{brief['id']}* — {risk_emoji} {brief.get('risk_level', '?')}",
        f"_{brief.get('created_at')}_",
        "",
        f"*{brief.get('title', '?')}*",
        "",
        f"{(brief.get('problem_summary') or '')[:400]}",
        "",
    ]
    if files:
        lines.append("*Dosyalar:*")
        for f in files[:10]:
            lines.append(f"  • `{f}`")
        if len(files) > 10:
            lines.append(f"  _+{len(files) - 10} daha_")
        lines.append("")
    diff = brief.get("proposed_diff") or ""
    if diff:
        preview = diff[:800]
        lines.append("*Değişiklik özeti:*")
        lines.append("```")
        lines.append(preview)
        if len(diff) > 800:
            lines.append("...")
        lines.append("```")
    lines.append("")
    lines.append("_Onaylamak için: 'brief #N onayla' / iptal için 'brief #N iptal'_")
    return "\n".join(lines)
