"""
Sentry Self-Awareness Monitor — Oturum 25.44 (Neo direktif 12 May)
====================================================================

Bot kendi gönderdiği Sentry event'lerini okuyup admin'e raporlar.

Mimari:
  Sentry SDK (sentry_sdk.init) → Sentry.io'ya event yazar (write-only)
  ↓
  Sentry REST API (Bearer token) ← BU MODÜL, hataları okur
  ↓
  Claude tool: get_sentry_errors(hours=24, limit=10)
  ↓
  Bot admin'e özet rapor verir

Token oluşturma (.env'ye SENTRY_API_TOKEN= ekle):
  1. https://de.sentry.io/settings/account/api/auth-tokens/ aç
  2. "Create New Token" → İsim: "FermatAI Bot Monitor"
  3. Scopes: event:read, project:read, org:read
  4. Token'ı kopyala (sntrys_... başlar), .env'ye ekle

API endpoint pattern:
  EU region: https://de.sentry.io/api/0/
  Org ID:    4511316121354240 (DSN'den)
  Project:   4511316129153104
"""
from __future__ import annotations
import os
import asyncio
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger


# ─── Git HEAD awareness (25.44-dev-meeting-2 konuşma analiz bulgusu) ─────────
# Bot meeting #7'de zombie Sentry issue önerdi (zaten fix'li olanı). Sebep:
# Sentry status 'unresolved' diye listede gözüküyor ama lastSeen fix commit'inden
# ÖNCE. Çözüm: her issue için HEAD commit zamanı ile karşılaştır, lastSeen
# eskisi ise 'fixed_likely=True' flag bırak.

_GIT_HEAD_CACHE = {"sha": None, "time": None, "fetched_at": None}
_GIT_CACHE_TTL = 60  # saniye


def _get_head_commit() -> tuple[Optional[str], Optional[datetime]]:
    """VPS'te git HEAD commit (sha kısa + UTC datetime). 60sn cache."""
    now = datetime.now(timezone.utc)
    if (_GIT_HEAD_CACHE["fetched_at"]
            and (now - _GIT_HEAD_CACHE["fetched_at"]).total_seconds() < _GIT_CACHE_TTL):
        return _GIT_HEAD_CACHE["sha"], _GIT_HEAD_CACHE["time"]
    try:
        # Repo root /opt/fermatai (VPS) veya local working dir
        repo_root = os.getenv("FERMATAI_REPO_ROOT", "/opt/fermatai")
        if not os.path.isdir(os.path.join(repo_root, ".git")):
            # Local dev (worktree) — bu dosyanın 2 üst dizini
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run(
            ["git", "log", "-1", "--format=%h|%ct"],
            cwd=repo_root, capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and "|" in r.stdout:
            sha, ts = r.stdout.strip().split("|", 1)
            commit_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            _GIT_HEAD_CACHE.update({"sha": sha, "time": commit_time, "fetched_at": now})
            return sha, commit_time
    except Exception as e:
        logger.debug(f"git HEAD lookup fail: {e}")
    _GIT_HEAD_CACHE["fetched_at"] = now  # negatif cache (5dk değil 60s)
    return None, None


def _is_likely_fixed(issue_last_seen: str, head_time: Optional[datetime]) -> bool:
    """Issue lastSeen'i HEAD commit zamanından önce ise muhtemelen fix'li.

    NOT: %100 garanti değil — sadece "Sentry dashboard'da resolved işaretle"
    önerisi için flag. Yanlış pozitif olabilir (issue tekrar tetiklenmeden
    günler geçmişse).
    """
    if not issue_last_seen or not head_time:
        return False
    try:
        # Sentry ISO: "2026-05-12T03:00:30Z" veya "...+00:00"
        s = issue_last_seen.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(s)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return last_dt < head_time
    except Exception:
        return False


def _humanize_delta(seconds: float) -> str:
    """Saniye → 'X saat/gün/dakika' Türkçe okunabilir."""
    s = abs(seconds)
    if s < 60:
        return f"{int(s)}sn"
    if s < 3600:
        return f"{int(s/60)}dk"
    if s < 86400:
        return f"{int(s/3600)}sa"
    return f"{int(s/86400)}g"


def _interpret_issue(last_seen: str, head_time: Optional[datetime],
                     fixed_likely: bool) -> str:
    """Bot yorum yükünü kaldırmak için her issue'ya açıklayıcı string.

    Bot 25.44-dev-meeting-2 #116927926 yorumunda 'bu sabah 03:00 hala
    tetiklendi' dedi — yanlış. Gerçek: lastSeen fix'ten ÖNCEYDİ, fix
    sonrası tetiklenmedi. Bu interpretation tool çıktısına direkt yazılır,
    bot kopyalayabilir.
    """
    if not last_seen or not head_time:
        return ""
    try:
        s = last_seen.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(s)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    now = datetime.now(timezone.utc)
    age_now = (now - last_dt).total_seconds()
    delta_to_head = (head_time - last_dt).total_seconds()
    if fixed_likely:
        # lastSeen < head_time → fix öncesi
        return (f"Son tetik: {_humanize_delta(age_now)} önce "
                f"(HEAD commit'ten {_humanize_delta(delta_to_head)} ÖNCE). "
                f"Fix sonrası YENİDEN tetiklenmedi — koddan fix'li, dashboard'dan resolved işaretle.")
    else:
        return (f"Son tetik: {_humanize_delta(age_now)} önce "
                f"(HEAD commit'ten {_humanize_delta(-delta_to_head)} SONRA). "
                f"AKTİF — kod değişikliğine rağmen tetiklenmeye devam ediyor.")


# ─── DSN → Org/Project çözümleme ─────────────────────────────────────────────

def _parse_sentry_dsn(dsn: str) -> dict:
    """DSN: https://{key}@o{org_id}.ingest.{region}.sentry.io/{project_id}

    Returns: {region, org_id, project_id, base_url}
    """
    if not dsn:
        return {}
    m = re.match(
        r"https?://([^@]+)@o(\d+)\.ingest\.(\w+\.)?sentry\.io/(\d+)",
        dsn.strip(),
    )
    if not m:
        return {}
    region = (m.group(3) or "").rstrip(".") or "us"  # de, us, eu
    base = f"https://{region}.sentry.io" if region != "us" else "https://sentry.io"
    return {
        "key": m.group(1),
        "org_id": m.group(2),
        "region": region,
        "project_id": m.group(4),
        "base_url": base,
    }


# ─── Cache (5dk TTL — Sentry rate limit nazik) ────────────────────────────────

_CACHE = {"data": None, "fetched_at": None}
_CACHE_TTL_SEC = 300


def _cache_fresh() -> bool:
    if not _CACHE["fetched_at"]:
        return False
    age = (datetime.now(timezone.utc) - _CACHE["fetched_at"]).total_seconds()
    return age < _CACHE_TTL_SEC


# ─── Public: Issue listesi ────────────────────────────────────────────────────

async def get_sentry_issues(
    hours: int = 24,
    limit: int = 20,
    use_cache: bool = True,
) -> dict:
    """Son N saat içindeki Sentry issue'larını çek.

    Args:
        hours: 1, 24, 168 (7d), vb.
        limit: max issue (Sentry default 25, max 100)
        use_cache: 5dk cache kullan

    Returns:
        {
          ok: bool,
          issues: [{title, culprit, level, status, count, last_seen, permalink, ...}],
          total: int,
          stats_period: "24h",
          fetched_at: ISO,
          error: str|None
        }
    """
    if use_cache and _cache_fresh() and _CACHE["data"]:
        return {**_CACHE["data"], "cached": True}

    token = os.getenv("SENTRY_API_TOKEN", "").strip()
    dsn = os.getenv("SENTRY_DSN", "").strip()

    if not token:
        return {
            "ok": False,
            "issues": [],
            "error": (
                "SENTRY_API_TOKEN eksik. .env'ye ekle: "
                "https://de.sentry.io/settings/account/api/auth-tokens/ → "
                "Create New Token (scopes: event:read, project:read, org:read)"
            ),
        }
    if not dsn:
        return {"ok": False, "issues": [], "error": "SENTRY_DSN tanımlı değil"}

    dsn_info = _parse_sentry_dsn(dsn)
    if not dsn_info.get("project_id"):
        return {"ok": False, "issues": [], "error": f"DSN parse fail: {dsn[:50]}"}

    org_slug = os.getenv("SENTRY_ORG_SLUG", "").strip()
    base = dsn_info["base_url"]

    # Stats period normalize
    if hours <= 1:
        stats = "1h"
    elif hours <= 24:
        stats = "24h"
    elif hours <= 168:
        stats = "7d"
    elif hours <= 720:
        stats = "30d"
    else:
        stats = "90d"

    async with httpx.AsyncClient(timeout=15) as client:
        # Önce org_slug yoksa user/me'den çek
        if not org_slug:
            try:
                r = await client.get(
                    f"{base}/api/0/organizations/",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if r.status_code == 200:
                    orgs = r.json() or []
                    if orgs:
                        org_slug = orgs[0].get("slug", "")
            except Exception as e:
                return {"ok": False, "issues": [], "error": f"Org list fail: {e}"}

        if not org_slug:
            return {
                "ok": False,
                "issues": [],
                "error": "Org slug bulunamadı (.env SENTRY_ORG_SLUG ile manuel ekle)",
            }

        # Issues endpoint
        try:
            r = await client.get(
                f"{base}/api/0/organizations/{org_slug}/issues/",
                params={
                    "project": dsn_info["project_id"],
                    "statsPeriod": stats,
                    "limit": min(int(limit), 100),
                    "sort": "freq",  # frequency desc — en çok tekrar eden üstte
                    "query": "is:unresolved",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                return {
                    "ok": False,
                    "issues": [],
                    "error": f"Sentry API {r.status_code}: {r.text[:200]}",
                }
            raw = r.json() or []
        except Exception as e:
            return {"ok": False, "issues": [], "error": f"API call fail: {e}"}

    # Issue'ları compact'la
    head_sha, head_time = _get_head_commit()
    issues = []
    for it in raw:
        last_seen = it.get("lastSeen", "")
        fixed_likely = _is_likely_fixed(last_seen, head_time)
        issues.append({
            "id":          it.get("id"),
            "title":       (it.get("title") or "")[:200],
            "culprit":     (it.get("culprit") or "")[:160],
            "level":       it.get("level", "error"),
            "status":      it.get("status", "unresolved"),
            "count":       int(it.get("count", 0) or 0),
            "user_count":  int(it.get("userCount", 0) or 0),
            "last_seen":   last_seen,
            "first_seen":  it.get("firstSeen", ""),
            "permalink":   it.get("permalink", ""),
            "metadata":    it.get("metadata", {}),
            # 25.44-dev-meeting-2 (13 May, konuşma analiz): fix commit'ten
            # önce tetiklenmiş ise zombie issue olabilir.
            "fixed_likely": fixed_likely,
            "interpretation": _interpret_issue(last_seen, head_time, fixed_likely),
        })

    result = {
        "ok": True,
        "issues": issues,
        "total": len(issues),
        "stats_period": stats,
        "org_slug": org_slug,
        "project_id": dsn_info["project_id"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "head_commit": head_sha or "",
        "head_commit_time": head_time.isoformat() if head_time else "",
    }
    _CACHE["data"] = result
    _CACHE["fetched_at"] = datetime.now(timezone.utc)
    return result


# ─── Compact özet (LLM prompt'a uygun) ─────────────────────────────────────

async def get_summary_for_prompt(hours: int = 24, limit: int = 5) -> str:
    """LLM system prompt'a enjekte için kısa metin özet."""
    r = await get_sentry_issues(hours=hours, limit=limit)
    if not r.get("ok"):
        # Token yoksa sessiz ol (system prompt'u kirletme)
        return ""
    issues = r.get("issues") or []
    if not issues:
        return f"📊 Sentry son {r.get('stats_period')}: temiz, hata yok ✅"
    # 25.44-dev-meeting-2: fix'li görünen zombie issue'ları ayrı say
    zombies = [it for it in issues if it.get("fixed_likely")]
    actives = [it for it in issues if not it.get("fixed_likely")]
    lines = [f"📊 Sentry son {r.get('stats_period')} — {len(actives)} aktif"
             + (f" + {len(zombies)} muhtemelen koddan fix'li (resolved işaretle)" if zombies else "")
             + ":"]
    for i, it in enumerate(issues[:limit], 1):
        title = it["title"][:80]
        cnt = it["count"]
        usr = it["user_count"]
        lvl = it["level"]
        flag = " ⚠ZOMBIE" if it.get("fixed_likely") else ""
        lines.append(f"  {i}. [{lvl}] {title} ({cnt}× / {usr} user){flag}")
    if zombies:
        lines.append("  💡 ZOMBIE = lastSeen < HEAD commit zamanı, koddan fix'li olabilir, "
                     "Sentry dashboard'dan resolved işaretle (veya resolve_issue tool çağır).")
    return "\n".join(lines)


# ─── Issue Resolve (25.44-dev-meeting-2 — event:write scope gerekli) ────────

async def resolve_issue(issue_id: str, reason: str = "Auto-resolved by bot") -> dict:
    """Sentry issue status'unu resolved'a çek. Token'ın event:write scope'u olmalı.

    Args:
        issue_id: Sentry numeric issue ID (str veya int kabul eder)
        reason: Activity log için yorum (opsiyonel)

    Returns:
        {ok: bool, issue_id, status, error}
    """
    token = os.getenv("SENTRY_API_TOKEN", "").strip()
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not token:
        return {"ok": False, "error": "SENTRY_API_TOKEN yok"}
    if not dsn:
        return {"ok": False, "error": "SENTRY_DSN yok"}
    dsn_info = _parse_sentry_dsn(dsn)
    if not dsn_info.get("base_url"):
        return {"ok": False, "error": f"DSN parse fail"}
    base = dsn_info["base_url"]
    iid = str(issue_id).strip()
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.put(
                f"{base}/api/0/issues/{iid}/",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"status": "resolved"},
            )
            if r.status_code == 200:
                # Cache invalide et — bir sonraki get_sentry_issues fresh okusun
                _CACHE["fetched_at"] = None
                return {"ok": True, "issue_id": iid, "status": "resolved"}
            if r.status_code == 403:
                return {"ok": False, "issue_id": iid,
                        "error": "403 Forbidden — token event:write scope'u yok. "
                                 "Yeni token oluştur: de.sentry.io/settings/account/api/auth-tokens/"}
            return {"ok": False, "issue_id": iid,
                    "error": f"Sentry API {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"ok": False, "issue_id": iid, "error": f"PUT fail: {e}"}


async def resolve_zombie_issues(hours: int = 168, dry_run: bool = True) -> dict:
    """fixed_likely=True olan tüm issue'ları topluca resolved'a çek.

    Args:
        hours: tarama penceresi (default 7 gün)
        dry_run: True ise sadece listeler, kapatmaz

    Returns:
        {ok, attempted, resolved, failed, items: [{id, title, result}]}
    """
    r = await get_sentry_issues(hours=hours, limit=100, use_cache=False)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}
    zombies = [it for it in r.get("issues", []) if it.get("fixed_likely")]
    out = {"ok": True, "attempted": len(zombies), "resolved": 0,
           "failed": 0, "dry_run": dry_run, "items": []}
    for z in zombies:
        if dry_run:
            out["items"].append({"id": z["id"], "title": z["title"][:80],
                                 "last_seen": z["last_seen"], "would_resolve": True})
            continue
        res = await resolve_issue(z["id"], reason=f"Auto: lastSeen={z['last_seen']} < HEAD")
        if res.get("ok"):
            out["resolved"] += 1
        else:
            out["failed"] += 1
        out["items"].append({"id": z["id"], "title": z["title"][:80], "result": res})
    return out


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/opt/fermatai/.env", override=True)

    async def _main():
        r = await get_sentry_issues(hours=24, limit=20, use_cache=False)
        if not r.get("ok"):
            print(f"❌ {r.get('error')}")
            return
        print(f"✅ {r['total']} issue, period={r['stats_period']}, org={r.get('org_slug')}")
        for it in r["issues"][:10]:
            print(f"  [{it['level']}] {it['title']} — {it['count']}× last={it['last_seen']}")
        print("\n=== PROMPT ÖZET ===")
        print(await get_summary_for_prompt(hours=24))

    asyncio.run(_main())
