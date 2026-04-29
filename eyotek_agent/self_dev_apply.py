"""
Self-Dev Apply (Oturum 25.29 — Evre 2.1)
==========================================

Brief'leri _drafts/ klasörüne unified diff + summary olarak yazar.
Production kodu HİÇ DEĞİŞTİRMEZ. Sadece sandbox.

Akış:
  Neo: "brief #5 draft yap"
   → apply_brief(brief_id=5)
      1. brief'i DB'den oku
      2. LLM'e: "bu pseudo-diff'i unified git diff'e çevir, gerçek dosya içerikleriyle"
      3. _drafts/{brief_id}_{tarih}.diff yaz (sandbox)
      4. _drafts/{brief_id}_summary.md yaz (insanı için)
      5. brief.status = 'drafted'
   → Neo'ya: "Draft hazır. Claude Code'da: cd /opt/fermatai && git apply _drafts/5_*.diff"

Evre 2.2'de bu .diff dosyasi otomatik git push + PR draft'a evrilir.
"""
from __future__ import annotations
import os
import re
import json
import time
from datetime import datetime
from pathlib import Path

from loguru import logger


# ─── Konfigürasyon ──────────────────────────────────────────────────────────

# _drafts klasörü — sandbox path
DRAFTS_ROOT = "/opt/fermatai/eyotek_agent/_drafts"

# Beyaz liste — bot bu dosyalara değişiklik önerebilir (apply_brief dosya tespit ederse)
APPLY_WHITELIST = [
    "eyotek_agent/fast_responses.py",
    "eyotek_agent/conversation_memory.py",
    "eyotek_agent/student_scenarios.py",
    "eyotek_agent/student_query_registry.py",
    "eyotek_agent/intent_parser.py",
    "eyotek_agent/context_engine.py",
    "KALDIGIM.md",
    "tests/",  # tüm test dosyaları
]

# Kara liste — apply_brief BUNLAR'a yazma talebi gelirse REDDEDER
APPLY_BLACKLIST = [
    "system_prompts.py",
    "whatsapp_bridge.py",
    "tool_definitions.py",      # bot kendi yetkisini değiştiremez
    "role_access.py",
    "self_dev_tools.py",        # bot kendi sandbox'ını değiştiremez
    "self_dev_apply.py",
    "self_dev_brief.py",
    ".env",
    ".key",
    ".pem",
    ".sql",
    "migrations/",
    ".service",
    ".timer",
    "requirements.txt",         # paket eklenemez
    ".github/",
    "Dockerfile",
    "docker-compose",
    "fermat_core_agent.py",     # ana agent loop, bot değiştiremez
]

# Limitler
MAX_DRAFT_SIZE = 100_000        # tek diff max 100KB
MAX_DRAFTS_PER_DAY = 20         # günlük quota


def _is_path_in_blacklist(path: str) -> tuple[bool, str]:
    """Path kara listede mi?"""
    p = (path or "").lower()
    for bad in APPLY_BLACKLIST:
        if bad.lower() in p:
            return True, bad
    return False, ""


def _is_path_in_whitelist(path: str) -> bool:
    """Path beyaz listede mi?"""
    p = (path or "").lower()
    for good in APPLY_WHITELIST:
        if good.lower() in p:
            return True
    return False


def _sanitize_filename(name: str) -> str:
    """Dosya adı için güvenli formata çevir."""
    name = re.sub(r"[^a-zA-Z0-9._\-]", "_", name)[:80]
    return name


def _ensure_drafts_root():
    """_drafts klasörünü oluştur (yoksa)."""
    os.makedirs(DRAFTS_ROOT, exist_ok=True)
    # README ekle (ilk seferinde) — repo'ya commit edilmez ama amaç açık olsun
    readme = os.path.join(DRAFTS_ROOT, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write(
                "# Self-Dev Drafts (Evre 2.1)\n\n"
                "Bot bu klasöre brief'lerden üretilen unified diff dosyalarını yazar.\n"
                "Production kodu BURADA DEĞİŞTİRİLMEZ. Bu sadece sandbox.\n\n"
                "Uygulamak için Claude Code'da:\n"
                "```\n"
                "cd /opt/fermatai && git apply eyotek_agent/_drafts/{N}_*.diff\n"
                "```\n"
            )


async def _check_daily_quota(triggered_by: str) -> tuple[bool, int]:
    """Günde kaç draft yapıldı? Kontrol."""
    from db_pool import db_fetchval
    try:
        n = await db_fetchval(
            """SELECT COUNT(*) FROM self_dev_audit
               WHERE actor_phone = $1
                 AND tool_name = 'apply_brief'
                 AND success = true
                 AND created_at > NOW() - INTERVAL '24 hours'""",
            triggered_by,
        ) or 0
        return (int(n) < MAX_DRAFTS_PER_DAY), int(n)
    except Exception:
        return True, 0


# ─── ANA API ────────────────────────────────────────────────────────────────

async def apply_brief(brief_id: int, _caller_phone: str = "") -> dict:
    """Brief'i _drafts/'a unified diff olarak yaz.

    Args:
        brief_id: self_dev_briefs.id
        _caller_phone: Tetikleyen (admin)

    Returns:
        {ok, draft_path, summary_path, files, risk, message}
    """
    # Pipeline aktif mi
    from self_dev_tools import _is_pipeline_active, _audit
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali. Neo 'self dev ac' yazabilir."}

    # Daily quota
    ok_quota, n_today = await _check_daily_quota(_caller_phone)
    if not ok_quota:
        await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False,
                     blocked_by="daily_quota_exceeded")
        return {"error": f"Günlük draft kotası doldu ({n_today}/{MAX_DRAFTS_PER_DAY})."}

    # Brief'i çek
    from self_dev_brief import get_brief
    brief = await get_brief(int(brief_id))
    if not brief:
        return {"error": f"Brief #{brief_id} bulunamadi"}
    if brief.get("status") in ("applied",):
        return {"error": f"Brief #{brief_id} zaten 'applied' durumunda"}

    # Files kara liste kontrolu
    files = brief.get("files_touched") or []
    blacklisted = []
    whitelisted = []
    other = []
    for f in files:
        in_bl, bl_match = _is_path_in_blacklist(f)
        if in_bl:
            blacklisted.append((f, bl_match))
            continue
        if _is_path_in_whitelist(f):
            whitelisted.append(f)
        else:
            other.append(f)

    if blacklisted:
        bl_str = ", ".join(f"{f} ({m})" for f, m in blacklisted)
        await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False,
                     blocked_by=f"blacklist:{bl_str}")
        return {
            "error": "Kara liste dosyalar tespit edildi — apply edilemez",
            "blacklisted": blacklisted,
            "hint": "Bu dosyalar (system_prompts/whatsapp_bridge/.env vs) bot tarafından "
                    "değiştirilemez. Manuel ele al.",
        }

    if not whitelisted and not other:
        return {"error": "Brief'te değiştirilecek dosya yok"}

    # _drafts hazırla
    _ensure_drafts_root()

    # LLM ile unified diff üret
    diff_text, llm_meta = await _generate_unified_diff(brief, whitelisted + other)
    if not diff_text:
        await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False,
                     error="llm_diff_empty")
        return {"error": "LLM diff üretemedi", "llm_meta": llm_meta}

    if len(diff_text) > MAX_DRAFT_SIZE:
        await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False,
                     blocked_by="diff_too_large")
        return {"error": f"Diff çok büyük ({len(diff_text)} byte > {MAX_DRAFT_SIZE})"}

    # Final blacklist re-check (LLM hayal ettiyse)
    diff_files = _extract_files_from_diff(diff_text)
    for df in diff_files:
        in_bl, bl_match = _is_path_in_blacklist(df)
        if in_bl:
            await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False,
                         blocked_by=f"diff_contains_blacklist:{bl_match}")
            return {
                "error": f"LLM çıktısı kara liste dosyasına dokundu: {df} ({bl_match})",
                "diff_files": diff_files,
            }

    # Yaz: .diff + summary.md
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    diff_filename = f"{brief_id}_{timestamp}.diff"
    summary_filename = f"{brief_id}_{timestamp}_summary.md"
    diff_path = os.path.join(DRAFTS_ROOT, diff_filename)
    summary_path = os.path.join(DRAFTS_ROOT, summary_filename)

    try:
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)

        summary = _build_summary(brief, diff_files, diff_text, llm_meta)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
    except Exception as e:
        await _audit(_caller_phone, "apply_brief", {"brief_id": brief_id}, False, error=str(e))
        return {"error": f"Yazma hatasi: {str(e)[:200]}"}

    # Brief status update
    from self_dev_brief import update_brief_status
    await update_brief_status(brief_id, "drafted",
                               notes=f"Draft: {diff_filename}")

    # Audit
    await _audit(_caller_phone, "apply_brief",
                 {"brief_id": brief_id, "diff_path": diff_path,
                  "files": diff_files},
                 True, bytes_read=len(diff_text))

    return {
        "ok": True,
        "brief_id": brief_id,
        "draft_path": diff_path,
        "summary_path": summary_path,
        "files": diff_files,
        "risk": brief.get("risk_level", "unknown"),
        "diff_lines": diff_text.count("\n"),
        "diff_bytes": len(diff_text),
        "message": (
            f"Draft hazır. Uygulamak için:\n"
            f"  cd /opt/fermatai && git apply {diff_path}\n"
            f"  # veya Claude Code'a: 'apply diff at {diff_path}'"
        ),
    }


def _extract_files_from_diff(diff_text: str) -> list[str]:
    """Unified diff'ten dosya adlarını çıkar."""
    files = set()
    # Format: "diff --git a/path b/path" veya "+++ b/path"
    for line in diff_text.splitlines():
        m = re.match(r"^diff --git a/(\S+) b/", line)
        if m:
            files.add(m.group(1))
            continue
        m2 = re.match(r"^\+\+\+ b/(\S+)", line)
        if m2:
            files.add(m2.group(1))
    return sorted(files)


def _build_summary(brief: dict, diff_files: list[str], diff_text: str,
                   llm_meta: dict) -> str:
    """Insan-okunabilir özet markdown."""
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(
        brief.get("risk_level", ""), "⚪"
    )
    diff_lines = diff_text.count("\n")
    additions = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    deletions = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))

    lines = [
        f"# Brief #{brief['id']} — {brief.get('title', '?')}",
        "",
        f"**Risk:** {risk_emoji} {brief.get('risk_level', '?')}",
        f"**Tetikleyen:** {brief.get('triggered_by', '?')}",
        f"**Oluşturma:** {brief.get('created_at')}",
        f"**Diff istatistik:** {len(diff_files)} dosya, {additions} ekleme, {deletions} silme",
        "",
        "## Problem",
        brief.get("problem_summary", "_(bilgi yok)_"),
        "",
        "## Etkilenen Dosyalar",
    ]
    for f in diff_files:
        lines.append(f"- `{f}`")
    lines.extend([
        "",
        "## Uygulama",
        "```bash",
        f"cd /opt/fermatai && git apply eyotek_agent/_drafts/{brief['id']}_*.diff",
        "```",
        "",
        "## Test (uyguladıktan sonra)",
        "```bash",
        ".venv/bin/python -m pytest tests/ -x",
        "```",
        "",
        "## Geri alma (rollback)",
        "```bash",
        f"cd /opt/fermatai && git apply -R eyotek_agent/_drafts/{brief['id']}_*.diff",
        "```",
        "",
        "## LLM meta",
        f"- Model: {llm_meta.get('model', '?')}",
        f"- Sure: {llm_meta.get('elapsed', 0):.1f}s",
        f"- Token (yaklasik): {llm_meta.get('approx_tokens', 0)}",
    ])
    return "\n".join(lines)


async def _generate_unified_diff(brief: dict, files_to_change: list[str]) -> tuple[str, dict]:
    """Brief + gerçek dosya içerikleri → LLM → unified git diff format.

    Returns: (diff_text, meta)
    """
    from self_dev_tools import read_file as _read_file

    # Mevcut dosya içerikleri (LLM context için)
    # Path key'i HER ZAMAN repo-relative olmalı (LLM diff'inde mutlak yol kullanmasin)
    file_contents: dict[str, str] = {}
    for f in files_to_change[:6]:  # max 6 dosya (token limiti)
        # Try absolute path
        candidates = [f]
        if not os.path.isabs(f):
            candidates.extend([
                os.path.join("/opt/fermatai", f),
                os.path.join("/opt/fermatai/eyotek_agent", f),
            ])
        # Repo-relative key hesapla
        rel_key = f
        if os.path.isabs(f):
            # /opt/fermatai/X/Y → X/Y
            rel_key = f.replace("/opt/fermatai/", "", 1).lstrip("/")
        elif f.startswith("opt/fermatai/"):
            rel_key = f.replace("opt/fermatai/", "", 1)
        for c in candidates:
            res = await _read_file(c, _caller_phone="self_dev_apply")
            if "error" not in res:
                file_contents[rel_key] = res.get("content", "")[:30000]  # 30KB/dosya
                break

    if not file_contents:
        return "", {"error": "no_files_readable"}

    # LLM prompt
    sys_prompt = """Sen FermatAI Self-Dev Apply asistanısın.

GORE V: Verilen brief + mevcut dosya içeriklerinden UNIFIED GIT DIFF üret.

KURALLAR:
1. Output SADECE unified diff formatinda (git apply ile uyumlu)
2. Format (PATH'LER REPO-RELATIVE — mutlak yol YASAK):
   ```
   diff --git a/eyotek_agent/conversation_memory.py b/eyotek_agent/conversation_memory.py
   --- a/eyotek_agent/conversation_memory.py
   +++ b/eyotek_agent/conversation_memory.py
   @@ -line,count +line,count @@
    context line
   -removed line
   +added line
    context line
   ```
3. PATH KURALI ŞART:
   - YASAK: a/opt/fermatai/eyotek_agent/...  (mutlak yol)
   - YASAK: a//opt/fermatai/...
   - DOĞRU: a/eyotek_agent/conversation_memory.py
   - DOĞRU: a/tests/test_route_regression.py
   - Verilen dosya yolu mutlak ise (/opt/fermatai/X/Y) → REPO-RELATIVE'e çevir (X/Y)
4. Her degisiklik icin yeterli context (3 satir uste, 3 satir alta)
5. Yorum ekleme, baska metin yazma
6. Eger degisiklik yapilamiyorsa veya brief belirsizse:
   "# CANNOT_GENERATE_DIFF: <sebep>" yaz
7. Gercek dosyalar disindaki satirlari ASLA degistirme — verilen icerige sadik kal
8. Hunk header satir numaralari MEVCUT dosya icerigine gore DOGRU olmali
   (yanlis line numbers → git apply --check fail → reddedilir)

ONEMLI:
- Eger brief soyut ise (gercek kod degisikligi anlatmiyorsa), cikti `# CANNOT_GENERATE_DIFF: <sebep>` olsun
- Eger dosyalardan biri eksik gorunuyorsa, sadece var olanlar icin diff yaz
- Verilen dosya icerigine BAKI degisikligi yap, hayal kurma
"""

    user_prompt_parts = [
        f"# BRIEF\n",
        f"Title: {brief.get('title', '')}\n",
        f"Problem: {brief.get('problem_summary', '')}\n",
        f"\n# PROPOSED CHANGES (psödo-diff)\n",
        f"{brief.get('proposed_diff', '')[:6000]}\n",
        f"\n# MEVCUT DOSYA İÇERİKLERİ\n",
    ]
    for fpath, content in file_contents.items():
        user_prompt_parts.append(f"\n## {fpath}\n```\n{content[:15000]}\n```\n")

    user_prompt = "".join(user_prompt_parts)

    # LLM çağrı (Claude — diff üretimi kalite gerektirir)
    from llm_router import LLMRouter
    router = LLMRouter()

    start = time.time()
    try:
        import asyncio as _asyncio
        resp = await _asyncio.to_thread(
            router.chat_cloud,
            [{"role": "user", "content": user_prompt[:120000]}],
            sys_prompt,
            None,
            "",
        )
        raw = "\n".join(b.text for b in resp.content if hasattr(b, "text"))
        elapsed = time.time() - start

        # Diff temizliği — code block içinden çek (markdown ihtimali)
        m = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", raw, re.DOTALL)
        if m:
            raw = m.group(1)

        # Cannot generate kontrolu
        if raw.strip().startswith("# CANNOT_GENERATE_DIFF"):
            return "", {"error": raw.strip()[:200], "elapsed": elapsed}

        # Diff satırları sayma (validity check)
        if "diff --git" not in raw and "+++" not in raw:
            return "", {"error": "llm_output_not_diff", "elapsed": elapsed,
                        "preview": raw[:300]}

        return raw.strip() + "\n", {
            "model": "claude-sonnet-4-6",
            "elapsed": elapsed,
            "approx_tokens": len(user_prompt) // 4,
        }
    except Exception as e:
        return "", {"error": str(e)[:200]}


# ─── Yardımcı listele/oku/sil ───────────────────────────────────────────────

async def list_drafts() -> dict:
    """_drafts/ klasöründeki tüm taslakları listele."""
    if not os.path.isdir(DRAFTS_ROOT):
        return {"drafts": []}
    items = []
    for entry in sorted(os.listdir(DRAFTS_ROOT)):
        if entry.startswith("."):
            continue
        full = os.path.join(DRAFTS_ROOT, entry)
        if os.path.isfile(full) and entry.endswith(".diff"):
            stat = os.stat(full)
            # Brief ID parse
            m = re.match(r"^(\d+)_", entry)
            brief_id = int(m.group(1)) if m else None
            items.append({
                "filename": entry,
                "path": full,
                "brief_id": brief_id,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            })
    return {"drafts": items, "count": len(items)}


async def read_draft(brief_id: int) -> dict:
    """Bir brief'in en son draft .diff içeriğini oku."""
    if not os.path.isdir(DRAFTS_ROOT):
        return {"error": "_drafts/ yok"}
    candidates = sorted(
        [n for n in os.listdir(DRAFTS_ROOT)
         if re.match(rf"^{int(brief_id)}_.*\.diff$", n)],
        reverse=True,
    )
    if not candidates:
        return {"error": f"Brief #{brief_id} icin draft bulunamadi"}

    path = os.path.join(DRAFTS_ROOT, candidates[0])
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {
            "brief_id": brief_id,
            "path": path,
            "filename": candidates[0],
            "content": content[:30000],
            "size": len(content),
            "truncated": len(content) > 30000,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


async def delete_draft(brief_id: int, _caller_phone: str = "") -> dict:
    """Bir brief'in draft dosyalarını sil (rollback için)."""
    if not os.path.isdir(DRAFTS_ROOT):
        return {"deleted": 0}
    deleted = []
    for entry in os.listdir(DRAFTS_ROOT):
        if re.match(rf"^{int(brief_id)}_", entry):
            full = os.path.join(DRAFTS_ROOT, entry)
            try:
                os.remove(full)
                deleted.append(entry)
            except Exception:
                continue

    # Brief status geri al (drafted → draft)
    if deleted:
        from self_dev_brief import update_brief_status
        await update_brief_status(brief_id, "discarded",
                                   notes=f"Draft silindi: {len(deleted)} dosya")

    from self_dev_tools import _audit
    await _audit(_caller_phone, "delete_draft",
                 {"brief_id": brief_id, "files": deleted},
                 True, bytes_read=0)
    return {"brief_id": brief_id, "deleted": deleted, "count": len(deleted)}


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        print(f"DRAFTS_ROOT: {DRAFTS_ROOT}")
        print(f"  exists: {os.path.isdir(DRAFTS_ROOT)}")
        _ensure_drafts_root()
        print(f"  exists after ensure: {os.path.isdir(DRAFTS_ROOT)}")
        print()

        # Whitelist/blacklist test
        print("=== Path classification test ===")
        for p in [
            "eyotek_agent/conversation_memory.py",       # whitelist
            "eyotek_agent/system_prompts.py",            # blacklist
            "eyotek_agent/whatsapp_bridge.py",           # blacklist
            "eyotek_agent/random_new_file.py",           # other
            "/opt/fermatai/.env",                        # blacklist
            "tests/test_route_regression.py",            # whitelist
        ]:
            in_bl, bl_match = _is_path_in_blacklist(p)
            in_wl = _is_path_in_whitelist(p)
            tag = "BLACK" if in_bl else ("WHITE" if in_wl else "other")
            print(f"  [{tag:5s}] {p}  {f'(reason: {bl_match})' if in_bl else ''}")

        # List drafts
        print()
        print("=== list_drafts ===")
        r = await list_drafts()
        print(f"  count: {r['count']}")

    asyncio.run(_test())
