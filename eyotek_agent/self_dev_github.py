"""
Self-Dev GitHub PR Draft (Oturum 25.29 — Evre 2.3)
====================================================

Bot bot/draft-* branch'i GitHub'a push ettikten sonra otomatik PR draft açar.
Neo telefondan link alır, GitHub UI'da review + merge yapar.

PR HER ZAMAN draft=true (merge edilemez).
Bot kendi PR'ını MERGE EDEMEZ — bu Evre 3 kapsamı.

Gerekli:
  - GITHUB_TOKEN env var (fine-grained PAT)
    Permissions: Contents: write, Pull requests: write, Metadata: read
    Repository: zekigoksal-source/fermatai (sadece bu)

Yoksa: graceful skip + kurulum talimatı.

Vizyon:
  Evre 2.1: brief → diff sandbox
  Evre 2.2: branch + commit + push (lokal hazır, push flag-gated)
  Evre 2.3: ← BU MODUL → PR draft GitHub'da
  Evre 2.4: pytest sonucu PR yorumuna
  Evre 3:   Atlas → otomatik gece self-dev
"""
from __future__ import annotations
import os
import re
import json
import time
from datetime import datetime
from typing import Optional

from loguru import logger

try:
    import httpx
except ImportError:
    httpx = None


# ─── Konfigürasyon ──────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"
REPO_OWNER = "zekigoksal-source"
REPO_NAME = "fermatai"
DEFAULT_BASE_BRANCH = "main"

# Hardcoded güvenlik
ALLOWED_HEAD_PATTERN = re.compile(r"^bot/draft-\d{8}-\d+$")
ALLOWED_BASE_BRANCHES = {"main"}  # PR sadece main'e açılabilir
PR_DRAFT_HARDCODED = True          # Merge edilemez PR

# Daily quota
MAX_PRS_PER_DAY = 10


def _get_token() -> Optional[str]:
    """GITHUB_TOKEN env'den oku. Yoksa None."""
    return (os.getenv("GITHUB_TOKEN") or "").strip() or None


def _mask_token(token: str) -> str:
    """Audit log için token'ı maskeleyerek göster."""
    if not token:
        return ""
    if len(token) > 12:
        return token[:4] + "***" + token[-3:]
    return "***"


async def _audit_pr(actor: str, action: str, args: dict, success: bool,
                     error: str = "", blocked_by: str = ""):
    """self_dev_audit'e yaz (mevcut audit kullanır)."""
    from self_dev_tools import _audit
    # args içinde token varsa maskele
    safe_args = {k: v for k, v in (args or {}).items() if k.lower() != "token"}
    await _audit(actor, f"github_{action}", safe_args, success,
                  bytes_read=0, error=error[:300], blocked_by=blocked_by)


async def _check_daily_pr_quota(actor: str) -> tuple[bool, int]:
    """Günde kaç PR açıldı?"""
    from db_pool import db_fetchval
    try:
        n = await db_fetchval(
            """SELECT COUNT(*) FROM self_dev_audit
               WHERE actor_phone = $1
                 AND tool_name = 'github_create_pr_draft'
                 AND success = true
                 AND created_at > NOW() - INTERVAL '24 hours'""",
            actor,
        ) or 0
        return (int(n) < MAX_PRS_PER_DAY), int(n)
    except Exception:
        return True, 0


def _build_pr_body(brief: dict, branch: str, head_sha: str = "",
                   diff_files: list[str] = None) -> str:
    """PR body otomatik oluştur (markdown)."""
    risk = brief.get("risk_level", "?")
    risk_badge = {"low": "🟢 LOW", "medium": "🟡 MEDIUM", "high": "🔴 HIGH"}.get(risk, "⚪ UNKNOWN")
    diff_files = diff_files or brief.get("files_touched") or []

    lines = [
        "## 🤖 FermatAI Self-Dev — Otomatik PR Draft",
        "",
        f"**Brief:** #{brief['id']}",
        f"**Risk:** {risk_badge}",
        f"**Branch:** `{branch}`",
        f"**Tetikleyen:** Neo (admin)",
        f"**Oluşturma:** {brief.get('created_at')}",
        "",
        "---",
        "",
        "## 📋 Sorun",
        "",
        brief.get("problem_summary", "_(bilgi yok)_"),
        "",
        "## 📁 Etkilenen Dosyalar",
        "",
    ]
    for f in diff_files[:15]:
        lines.append(f"- `{f}`")
    if len(diff_files) > 15:
        lines.append(f"_+{len(diff_files) - 15} dosya daha_")

    lines.extend([
        "",
        "## 🔍 Decision Trace",
        "",
        f"```bash",
        f"# VPS'te bu PR'ın kararının izini sürmek için:",
        f"python eyotek_agent/decision_trace_query.py --signal 'brief={brief['id']}'",
        f"```",
        "",
        "## 🧪 Test Planı",
        "",
        "```bash",
        f"# Çalıştırılacak testler (Evre 2.4 sonrası otomatik olacak):",
        f"cd /opt/fermatai",
        f".venv/bin/python -m pytest tests/test_route_regression.py -v",
        f".venv/bin/python -m pytest tests/test_fast_response_core.py -v",
        f"```",
        "",
        "## ↩️ Rollback",
        "",
        "```bash",
        f"# Lokal'de geri almak için:",
        f"git checkout main && git branch -D {branch}",
        f"# Veya PR'ı kapat (merge yapmadan):",
        f"# Bu sayfanın altında 'Close pull request' butonu",
        "```",
        "",
        "---",
        "",
        "## ⚠️ Önemli",
        "",
        "- ✅ Bu PR **DRAFT** durumunda — merge edilemez",
        "- ✅ Bot `bot/draft-*` branch'inden açtı, `main` korunuyor",
        "- ✅ Production kodu HENÜZ değişmedi",
        "- ❌ Merge için **Neo manuel onay** gerek (GitHub UI: 'Ready for review' → 'Merge')",
        "",
        "## 🔐 Güvenlik Audit",
        "",
        f"Bu PR'ın tüm self-dev araç çağrıları audit edildi:",
        f"```sql",
        f"SELECT * FROM self_dev_audit WHERE args_jsonb->>'brief_id' = '{brief['id']}';",
        f"```",
        "",
        "---",
        "",
        "_🤖 Generated by FermatAI Self-Dev (Evre 2.3)_",
        "_Pipeline: brief → apply_brief → branch → commit → push → PR draft_",
    ])
    return "\n".join(lines)


# ─── ANA API ────────────────────────────────────────────────────────────────

async def create_pr_draft(brief_id: int, branch: str,
                            _caller_phone: str = "") -> dict:
    """bot/draft-* branch için PR draft aç."""
    from self_dev_tools import _is_pipeline_active
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali."}

    # httpx kontrol
    if httpx is None:
        return {"error": "httpx kurulu degil. pip install httpx"}

    # Token kontrol
    token = _get_token()
    if not token:
        await _audit_pr(_caller_phone, "create_pr_draft",
                         {"branch": branch}, False, blocked_by="no_github_token")
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_github_token",
            "message": (
                "GITHUB_TOKEN env yok — PR açılamaz.\n\n"
                "Kurulum:\n"
                "1. https://github.com/settings/tokens?type=beta\n"
                "2. 'Generate new token (fine-grained)'\n"
                "3. Repository access: zekigoksal-source/fermatai\n"
                "4. Permissions:\n"
                "   - Contents: Read & Write\n"
                "   - Pull requests: Read & Write\n"
                "   - Metadata: Read\n"
                "5. Token kopyala, VPS'te:\n"
                "   sudo nano /opt/fermatai/.env\n"
                "   GITHUB_TOKEN=ghp_xxx\n"
                "6. sudo systemctl restart fermatai-bridge.service"
            ),
        }

    # Branch pattern kontrol (HARDCODED)
    if not ALLOWED_HEAD_PATTERN.match(branch):
        await _audit_pr(_caller_phone, "create_pr_draft",
                         {"branch": branch}, False, blocked_by="invalid_branch")
        return {"error": f"Sadece bot/draft-* branch'lere PR. Verilen: {branch}"}

    # Daily quota
    ok_quota, n = await _check_daily_pr_quota(_caller_phone)
    if not ok_quota:
        await _audit_pr(_caller_phone, "create_pr_draft",
                         {"branch": branch}, False,
                         blocked_by=f"daily_quota:{n}/{MAX_PRS_PER_DAY}")
        return {"error": f"Günlük PR kotası doldu ({n}/{MAX_PRS_PER_DAY})"}

    # Brief'i çek
    from self_dev_brief import get_brief
    brief = await get_brief(int(brief_id))
    if not brief:
        return {"error": f"Brief #{brief_id} bulunamadi"}

    # Branch'in remote'da olup olmadığını kontrol et
    from self_dev_git import _run_git
    rc, out, err = _run_git(["ls-remote", "--heads", "origin", branch], timeout=15)
    if rc != 0 or branch not in out:
        return {
            "error": f"Branch {branch} remote'da yok. Once push yap.",
            "hint": "selfdev_push_branch tool ile push et, sonra PR ac.",
        }

    # PR title + body
    title = f"[Self-Dev] {brief.get('title', f'brief #{brief_id}')}"[:120]
    diff_files = brief.get("files_touched") or []
    body = _build_pr_body(brief, branch, diff_files=diff_files)

    # GitHub API call
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FermatAI-Self-Dev/0.1",
    }
    payload = {
        "title": title,
        "head": branch,
        "base": DEFAULT_BASE_BRANCH,    # HARDCODED: main
        "body": body,
        "draft": PR_DRAFT_HARDCODED,    # HARDCODED: true
        "maintainer_can_modify": True,
    }

    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/pulls"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except Exception as e:
        await _audit_pr(_caller_phone, "create_pr_draft",
                         {"branch": branch, "brief_id": brief_id}, False,
                         error=f"http_fail:{e}")
        return {"error": f"GitHub API erisimi basarisiz: {str(e)[:200]}"}

    if resp.status_code not in (200, 201):
        err_text = resp.text[:500]
        await _audit_pr(_caller_phone, "create_pr_draft",
                         {"branch": branch, "brief_id": brief_id}, False,
                         error=f"api_{resp.status_code}:{err_text[:200]}")
        return {
            "error": f"GitHub API HTTP {resp.status_code}",
            "details": err_text,
            "hint": (
                "401 → token yanlış / expired"
                if resp.status_code == 401 else
                "403 → token yetkisi yetersiz (Pull requests: write gerek)"
                if resp.status_code == 403 else
                "422 → branch zaten PR'a sahip / branch boş / aynı commit"
                if resp.status_code == 422 else
                "Detaya bak."
            ),
        }

    pr = resp.json()
    pr_number = pr.get("number")
    pr_url = pr.get("html_url")

    # Brief status update
    from self_dev_brief import update_brief_status
    await update_brief_status(brief_id, "reviewed",
                                applied_commit="",
                                notes=f"PR #{pr_number}: {pr_url}")

    await _audit_pr(_caller_phone, "create_pr_draft",
                     {"brief_id": brief_id, "branch": branch,
                      "pr_number": pr_number, "pr_url": pr_url}, True)

    return {
        "ok": True,
        "brief_id": brief_id,
        "branch": branch,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "draft": True,
        "message": f"✅ PR #{pr_number} draft acildi: {pr_url}",
    }


async def get_pr_status(pr_number: int, _caller_phone: str = "") -> dict:
    """Bir PR'ın durumunu sorgula."""
    if httpx is None:
        return {"error": "httpx yok"}
    token = _get_token()
    if not token:
        return {"error": "GITHUB_TOKEN yok"}

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FermatAI-Self-Dev/0.1",
    }
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{int(pr_number)}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
    except Exception as e:
        return {"error": str(e)[:200]}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    pr = resp.json()
    await _audit_pr(_caller_phone, "get_pr_status", {"pr_number": pr_number}, True)
    return {
        "pr_number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "mergeable": pr.get("mergeable"),
        "merged": pr.get("merged"),
        "head_branch": pr.get("head", {}).get("ref"),
        "base_branch": pr.get("base", {}).get("ref"),
        "url": pr.get("html_url"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
        "created_at": pr.get("created_at"),
    }


async def add_pr_comment(pr_number: int, body: str,
                          _caller_phone: str = "") -> dict:
    """PR'a yorum ekle (Evre 2.4 pytest sonucu vb)."""
    if httpx is None:
        return {"error": "httpx yok"}
    token = _get_token()
    if not token:
        return {"error": "GITHUB_TOKEN yok"}

    if not body or len(body) < 5:
        return {"error": "Yorum cok kisa"}

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FermatAI-Self-Dev/0.1",
    }
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{int(pr_number)}/comments"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json={"body": body[:60000]})
    except Exception as e:
        return {"error": str(e)[:200]}

    if resp.status_code not in (200, 201):
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    data = resp.json()
    await _audit_pr(_caller_phone, "add_pr_comment",
                     {"pr_number": pr_number, "body_len": len(body)}, True)
    return {
        "ok": True,
        "comment_id": data.get("id"),
        "comment_url": data.get("html_url"),
    }


async def close_pr(pr_number: int, _caller_phone: str = "") -> dict:
    """PR'ı kapat (merge etmeden). Bot kendi PR'ını iptal etmek isterse."""
    if httpx is None:
        return {"error": "httpx yok"}
    token = _get_token()
    if not token:
        return {"error": "GITHUB_TOKEN yok"}

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "FermatAI-Self-Dev/0.1",
    }
    url = f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{int(pr_number)}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # PR sahibi bot olduğunu doğrula (önce GET)
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"error": f"PR bulunamadı: HTTP {resp.status_code}"}
            pr_data = resp.json()
            head_branch = pr_data.get("head", {}).get("ref", "")
            if not ALLOWED_HEAD_PATTERN.match(head_branch):
                return {
                    "error": "Sadece bot/draft-* branch'li PR'lar kapatilabilir",
                    "head_branch": head_branch,
                }

            # PATCH state=closed
            resp = await client.patch(url, headers=headers, json={"state": "closed"})
    except Exception as e:
        return {"error": str(e)[:200]}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    await _audit_pr(_caller_phone, "close_pr", {"pr_number": pr_number}, True)
    return {"ok": True, "pr_number": pr_number, "state": "closed"}


# ─── Tek-tıkla Full Pipeline ─────────────────────────────────────────────────

async def full_pipeline(brief_id: int, _caller_phone: str = "") -> dict:
    """Brief → branch + apply + commit + push + PR draft (TEK ÇAĞRI).

    Adım hatasında ROLLBACK yapar (orphan branch kalmaz).
    """
    from self_dev_tools import _is_pipeline_active
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali."}

    steps_done = []

    # Step 1: branch + apply + commit (lokal)
    from self_dev_git import draft_to_local_branch, push_branch, delete_local_branch, _run_git
    r1 = await draft_to_local_branch(int(brief_id), _caller_phone=_caller_phone)
    if "error" in r1:
        return {"step": "draft_to_local_branch", **r1, "steps_done": steps_done}
    branch = r1["branch"]
    steps_done.append({"step": "branch_commit", "branch": branch, "sha": r1.get("sha")})

    # Step 2: push
    r2 = await push_branch(branch, _caller_phone=_caller_phone)
    if "error" in r2:
        # Cleanup: lokal branch sil
        await delete_local_branch(branch, _caller_phone=_caller_phone)
        return {"step": "push", "branch": branch, **r2,
                "steps_done": steps_done, "rolled_back": True}
    if r2.get("skipped"):
        return {
            "step": "push", "skipped": True, "reason": r2.get("reason"),
            "steps_done": steps_done,
            "branch": branch,
            "message": (
                f"Branch {branch} lokal'de hazır ama push KAPALI. "
                "Neo 'self dev push ac' demeli, sonra 'brief #N PR' tekrar dene."
            ),
        }
    steps_done.append({"step": "push", "branch": branch})

    # Step 3: PR draft
    r3 = await create_pr_draft(int(brief_id), branch, _caller_phone=_caller_phone)
    if "error" in r3:
        return {"step": "create_pr_draft", "branch": branch, **r3,
                "steps_done": steps_done}
    if r3.get("skipped"):
        return {
            "step": "create_pr_draft", "skipped": True,
            "reason": r3.get("reason"),
            "branch": branch,
            "steps_done": steps_done,
            "message": (
                f"Branch {branch} push edildi ama GITHUB_TOKEN yok. "
                "Neo'nun PAT kurması gerek. Kurulum talimatı: " + r3.get("message", "")
            ),
        }
    steps_done.append({"step": "pr_draft",
                       "pr_number": r3.get("pr_number"),
                       "pr_url": r3.get("pr_url")})

    return {
        "ok": True,
        "brief_id": brief_id,
        "branch": branch,
        "pr_number": r3.get("pr_number"),
        "pr_url": r3.get("pr_url"),
        "steps_done": steps_done,
        "message": (
            f"✅ Full pipeline tamamlandi.\n"
            f"   Brief #{brief_id} → branch + commit + push + PR draft\n"
            f"   PR: {r3.get('pr_url')}\n"
            f"   Tek tık merge için telefondan PR'a bak."
        ),
    }


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        print(f"GITHUB_TOKEN: {_mask_token(_get_token() or '')}")
        print(f"REPO: {REPO_OWNER}/{REPO_NAME}")
        print(f"BASE: {DEFAULT_BASE_BRANCH}")
        print(f"HEAD pattern: {ALLOWED_HEAD_PATTERN.pattern}")
        print()

        if not _get_token():
            print("Token yok — sadece dry-run.")
            print()
            print("=== Dry-run: PR body builder ===")
            fake_brief = {
                "id": 99,
                "title": "Test brief — fast_responses veda pattern",
                "risk_level": "medium",
                "problem_summary": "Görüşmek üzere yakalanmıyor.",
                "files_touched": ["eyotek_agent/fast_responses.py"],
                "created_at": "2026-04-30",
            }
            body = _build_pr_body(fake_brief, "bot/draft-20260430-1")
            print(body[:1500])
            print(f"\n... (toplam {len(body)} char)")
            return

        # Token var — gerçek API
        print("=== Real API test ===")
        # PR #1 status (varsayım)
        r = await get_pr_status(1)
        print(f"PR #1 status: {r}")

    asyncio.run(_test())
