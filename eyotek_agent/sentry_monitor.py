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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger


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
    issues = []
    for it in raw:
        issues.append({
            "id":          it.get("id"),
            "title":       (it.get("title") or "")[:200],
            "culprit":     (it.get("culprit") or "")[:160],
            "level":       it.get("level", "error"),
            "status":      it.get("status", "unresolved"),
            "count":       int(it.get("count", 0) or 0),
            "user_count":  int(it.get("userCount", 0) or 0),
            "last_seen":   it.get("lastSeen", ""),
            "first_seen":  it.get("firstSeen", ""),
            "permalink":   it.get("permalink", ""),
            "metadata":    it.get("metadata", {}),
        })

    result = {
        "ok": True,
        "issues": issues,
        "total": len(issues),
        "stats_period": stats,
        "org_slug": org_slug,
        "project_id": dsn_info["project_id"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
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
    lines = [f"📊 Sentry son {r.get('stats_period')} — {len(issues)} aktif issue (en çok tekrar):"]
    for i, it in enumerate(issues[:limit], 1):
        title = it["title"][:80]
        cnt = it["count"]
        usr = it["user_count"]
        lvl = it["level"]
        lines.append(f"  {i}. [{lvl}] {title} ({cnt}× / {usr} user)")
    return "\n".join(lines)


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
