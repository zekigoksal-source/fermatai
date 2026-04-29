"""
Self-Dev Pipeline — Evre 1 (Oturum 25.29)
==========================================

Bot kendi kodunu OKUYABILIR. Yazma henuz YOK (Evre 2'de gelecek).

8 read araci + sandbox + secret filter + audit log + kill switch.
Felsefe: Neo'nun "claude code'u API olarak kullanan bot" hissiyatini
yaratmaya doğru ilk adım — bot dosyalarini gercek goruyor, hayal kurmuyor.

ACL: Sadece admin (Neo). SGM (Orsel) icin kapaliyiz — sistem dosyalari kapali.

Vizyon: Jarvis → Vision → Ultron birlesimi (Neo'nun ifadesi)
  - Jarvis: Read + brief (Evre 1) ← BURADAYIZ
  - Vision: PR draft + sandbox write (Evre 2)
  - Ultron: Updater + auto-merge (Evre 3, dikkatli)
"""
from __future__ import annotations
import os
import re
import json
import asyncio
import subprocess
import time
from pathlib import Path
from typing import Optional

from loguru import logger


# ─── KONFIGÜRASYON ──────────────────────────────────────────────────────────

# Whitelisted root dizinler — bot yalniz bu yollardan okur
ALLOWED_READ_ROOTS = [
    "/opt/fermatai",                       # Production code
    "/var/log/fermatai",                   # Bot logları
    "C:/Users/zekig/OneDrive/Desktop/FermatAI",  # Local dev (Windows)
]

# Secret patterns — dosya yoluna gore engel
SECRET_FILE_PATTERNS = [
    r"\.env$", r"\.env\.\w+$",
    r"\.key$", r"\.pem$", r"\.crt$",
    r"id_rsa", r"id_ed25519", r"id_ecdsa",
    r"credentials?\.(json|yaml|yml|txt)$",
    r"secret",
    r"\.ssh/",
    r"\.aws/",
    r"\.gnupg/",
]

# Secret patterns — dosya icerigi maskeleme (read sirasi)
SECRET_LINE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|password|passwd|secret|token|access[_-]?key)\s*[=:]\s*['\"]?([^'\"\\s]{6,})", re.M),
    re.compile(r"(?i)(?:bearer|basic)\s+([A-Za-z0-9._\\-]{20,})", re.M),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),       # Anthropic / OpenAI keys
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),       # Groq keys
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),       # GitHub PAT
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS access key
]

# Read limitleri — abuse koruma
MAX_READ_BYTES = 200_000           # tek read max 200KB
MAX_GREP_RESULTS = 200
MAX_LIST_ENTRIES = 500
MAX_LOG_LINES = 1000

# Kill switch cache (3sn TTL — DB hit minimize)
_KILL_SWITCH_CACHE = {"value": None, "ts": 0}
_KILL_SWITCH_TTL = 3.0


# ─── HELPERS ────────────────────────────────────────────────────────────────

def _normalize_path(p: str) -> str:
    """Path'i absolute + normalize et."""
    try:
        return str(Path(p).resolve())
    except Exception:
        return p


def _is_allowed_path(path: str) -> tuple[bool, str]:
    """Yol whitelist'te mi? (allowed, reason)"""
    if not path:
        return False, "empty_path"
    norm = _normalize_path(path)
    # Symlink/relative escape onleme
    if ".." in path or path.startswith("~"):
        return False, "path_traversal"
    # Whitelist kontrol
    in_whitelist = any(
        norm.startswith(_normalize_path(root)) for root in ALLOWED_READ_ROOTS
    )
    if not in_whitelist:
        return False, "outside_sandbox"
    # Secret file pattern
    for pat in SECRET_FILE_PATTERNS:
        if re.search(pat, norm, re.IGNORECASE):
            return False, f"secret_file:{pat}"
    return True, "ok"


def _mask_secrets(content: str) -> tuple[str, int]:
    """Icerikteki secret pattern'leri maskele. (masked_content, hit_count)"""
    if not content:
        return content, 0
    hits = 0
    masked = content
    for pat in SECRET_LINE_PATTERNS:
        def _replace(m):
            nonlocal hits
            hits += 1
            full = m.group(0)
            # İlk 3 char + ... + son 2 char göster
            if len(full) > 8:
                return full[:3] + "***[MASKED]***" + full[-2:]
            return "***[MASKED]***"
        masked = pat.sub(_replace, masked)
    return masked, hits


async def _is_pipeline_active() -> bool:
    """Kill switch — sistem_ayar tablosundan oku, 3sn cache'le."""
    now = time.time()
    if _KILL_SWITCH_CACHE["ts"] + _KILL_SWITCH_TTL > now and _KILL_SWITCH_CACHE["value"] is not None:
        return _KILL_SWITCH_CACHE["value"]
    try:
        from db_pool import db_fetchval
        v = await db_fetchval(
            "SELECT value FROM sistem_ayar WHERE key = 'SELF_DEV_PIPELINE_ACTIVE'"
        )
        active = (str(v or "false").lower() == "true")
    except Exception:
        active = False
    _KILL_SWITCH_CACHE["value"] = active
    _KILL_SWITCH_CACHE["ts"] = now
    return active


def invalidate_killswitch_cache():
    """Neo 'self dev kapat' yazinca anında devreye girsin."""
    _KILL_SWITCH_CACHE["value"] = None
    _KILL_SWITCH_CACHE["ts"] = 0


async def _audit(actor_phone: str, tool: str, args: dict, success: bool,
                 bytes_read: int = 0, error: str = "", blocked_by: str = ""):
    """Audit log'a kayit (best-effort, hata fırlatmaz)."""
    try:
        from db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO self_dev_audit
                   (actor_phone, tool_name, args_jsonb, success, bytes_read, error_msg, blocked_by)
                   VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7)""",
                actor_phone or "unknown",
                tool,
                json.dumps(args, ensure_ascii=False, default=str)[:5000],
                success, bytes_read, (error or "")[:500], blocked_by,
            )
    except Exception as e:
        logger.debug(f"[SELFDEV-AUDIT] write fail: {e}")


# ─── 8 READ ARACI ───────────────────────────────────────────────────────────

async def read_file(path: str, lines: Optional[str] = None,
                    _caller_phone: str = "") -> dict:
    """Dosya icerigini oku (sandbox + secret mask).

    Args:
        path: Dosya yolu (whitelist icinde olmalı)
        lines: Opsiyonel satir araligi 'N-M' (orn '50-150')
    """
    if not await _is_pipeline_active():
        await _audit(_caller_phone, "read_file", {"path": path}, False, blocked_by="killswitch")
        return {"error": "Self-dev pipeline kapali. Neo 'self dev ac' yazabilir."}

    ok, reason = _is_allowed_path(path)
    if not ok:
        await _audit(_caller_phone, "read_file", {"path": path}, False, blocked_by=reason)
        return {"error": f"Sandbox engeli: {reason}", "path": path}

    try:
        with open(path, "rb") as f:
            data = f.read(MAX_READ_BYTES + 1)
        truncated = len(data) > MAX_READ_BYTES
        if truncated:
            data = data[:MAX_READ_BYTES]
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")

        # Satir araligi
        if lines:
            try:
                start_str, end_str = lines.split("-", 1)
                start_i = max(1, int(start_str))
                end_i = int(end_str)
                arr = text.splitlines(keepends=True)
                text = "".join(arr[start_i - 1:end_i])
            except Exception:
                pass

        # Secret mask
        masked, hits = _mask_secrets(text)

        await _audit(_caller_phone, "read_file",
                     {"path": path, "lines": lines}, True, bytes_read=len(masked))
        return {
            "path": path,
            "content": masked,
            "bytes": len(masked),
            "secrets_masked": hits,
            "truncated": truncated,
            "lines_filter": lines,
        }
    except FileNotFoundError:
        await _audit(_caller_phone, "read_file", {"path": path}, False, error="file_not_found")
        return {"error": "Dosya bulunamadi", "path": path}
    except Exception as e:
        await _audit(_caller_phone, "read_file", {"path": path}, False, error=str(e))
        return {"error": f"Okuma hatasi: {str(e)[:200]}", "path": path}


async def list_dir(path: str, glob_pattern: str = "*",
                   _caller_phone: str = "") -> dict:
    """Dizin icerigi (sandbox)."""
    if not await _is_pipeline_active():
        await _audit(_caller_phone, "list_dir", {"path": path}, False, blocked_by="killswitch")
        return {"error": "Self-dev pipeline kapali."}

    ok, reason = _is_allowed_path(path)
    if not ok:
        await _audit(_caller_phone, "list_dir", {"path": path}, False, blocked_by=reason)
        return {"error": f"Sandbox engeli: {reason}", "path": path}

    try:
        p = Path(path)
        if not p.is_dir():
            return {"error": "Dizin değil", "path": path}
        entries = []
        for entry in sorted(p.glob(glob_pattern or "*"))[:MAX_LIST_ENTRIES]:
            ok2, _ = _is_allowed_path(str(entry))
            if not ok2:
                continue
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                    "modified": int(stat.st_mtime),
                })
            except Exception:
                continue

        await _audit(_caller_phone, "list_dir",
                     {"path": path, "glob": glob_pattern}, True, bytes_read=len(entries) * 50)
        return {"path": path, "entries": entries, "count": len(entries)}
    except Exception as e:
        await _audit(_caller_phone, "list_dir", {"path": path}, False, error=str(e))
        return {"error": str(e)[:200]}


async def grep_repo(pattern: str, file_type: str = "py", limit: int = 50,
                    path: str = "/opt/fermatai/eyotek_agent",
                    _caller_phone: str = "") -> dict:
    """Repo'da regex ara — ripgrep kullan, fallback: Python re."""
    if not await _is_pipeline_active():
        await _audit(_caller_phone, "grep_repo", {"pattern": pattern}, False, blocked_by="killswitch")
        return {"error": "Self-dev pipeline kapali."}

    ok, reason = _is_allowed_path(path)
    if not ok:
        await _audit(_caller_phone, "grep_repo", {"pattern": pattern, "path": path}, False, blocked_by=reason)
        return {"error": f"Sandbox engeli: {reason}"}

    limit = min(int(limit or 50), MAX_GREP_RESULTS)
    results: list[dict] = []
    bytes_read = 0

    # Once ripgrep dene
    try:
        cmd = ["rg", "-n", "--no-heading", "-S"]
        if file_type:
            cmd.extend(["-t", file_type])
        cmd.extend([pattern, path])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, errors="replace")
        if proc.returncode in (0, 1):  # 1 = no match (normal)
            for line in proc.stdout.splitlines()[:limit]:
                # Format: "path:lineno:content"
                m = re.match(r"^([^:]+):(\d+):(.*)$", line)
                if m:
                    file_path = m.group(1)
                    ok_p, _ = _is_allowed_path(file_path)
                    if not ok_p:
                        continue
                    content_line, _ = _mask_secrets(m.group(3))
                    results.append({
                        "file": file_path,
                        "line": int(m.group(2)),
                        "content": content_line[:300],
                    })
                    bytes_read += len(line)
    except FileNotFoundError:
        # ripgrep yok — Python fallback
        try:
            file_glob = f"**/*.{file_type}" if file_type else "**/*"
            regex = re.compile(pattern)
            for fp in Path(path).rglob(file_glob):
                if len(results) >= limit:
                    break
                ok_p, _ = _is_allowed_path(str(fp))
                if not ok_p:
                    continue
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        for ln, line in enumerate(f, 1):
                            if regex.search(line):
                                content_line, _ = _mask_secrets(line.rstrip())
                                results.append({
                                    "file": str(fp),
                                    "line": ln,
                                    "content": content_line[:300],
                                })
                                bytes_read += len(line)
                                if len(results) >= limit:
                                    break
                except Exception:
                    continue
        except Exception as e:
            await _audit(_caller_phone, "grep_repo", {"pattern": pattern}, False, error=str(e))
            return {"error": f"Grep hatasi: {str(e)[:200]}"}
    except Exception as e:
        await _audit(_caller_phone, "grep_repo", {"pattern": pattern}, False, error=str(e))
        return {"error": f"Grep hatasi: {str(e)[:200]}"}

    await _audit(_caller_phone, "grep_repo",
                 {"pattern": pattern, "file_type": file_type, "limit": limit},
                 True, bytes_read=bytes_read)
    return {
        "pattern": pattern,
        "matches": results,
        "count": len(results),
        "truncated": len(results) >= limit,
    }


async def read_logs(service: str = "fermatai-bridge", lines: int = 50,
                    grep: str = "", _caller_phone: str = "") -> dict:
    """systemd service log'u (journalctl). Bot kendi loguna bakabilir."""
    if not await _is_pipeline_active():
        await _audit(_caller_phone, "read_logs", {"service": service}, False, blocked_by="killswitch")
        return {"error": "Self-dev pipeline kapali."}

    # Sadece fermatai-* servisleri
    if not service.startswith("fermatai-"):
        await _audit(_caller_phone, "read_logs", {"service": service}, False, blocked_by="non_fermatai_service")
        return {"error": "Sadece fermatai-* servisleri okunabilir"}

    lines = min(int(lines or 50), MAX_LOG_LINES)
    try:
        cmd = ["journalctl", "-u", f"{service}.service", "-n", str(lines), "--no-pager"]
        if grep:
            cmd.extend(["-g", grep])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, errors="replace")
        text = proc.stdout
        # Secret mask
        masked, hits = _mask_secrets(text)

        await _audit(_caller_phone, "read_logs",
                     {"service": service, "lines": lines, "grep": grep},
                     True, bytes_read=len(masked))
        return {
            "service": service,
            "lines_requested": lines,
            "content": masked[:30000],  # sınır
            "secrets_masked": hits,
            "exit_code": proc.returncode,
        }
    except FileNotFoundError:
        return {"error": "journalctl bulunamadi (sadece VPS'te calisir)"}
    except Exception as e:
        await _audit(_caller_phone, "read_logs", {"service": service}, False, error=str(e))
        return {"error": f"Log okuma hatasi: {str(e)[:200]}"}


async def git_diff(commit_or_branch: str = "HEAD", file: str = "",
                   _caller_phone: str = "") -> dict:
    """Git diff — son commit veya belirli branch/file karsilastirma."""
    if not await _is_pipeline_active():
        await _audit(_caller_phone, "git_diff", {}, False, blocked_by="killswitch")
        return {"error": "Self-dev pipeline kapali."}

    repo = "/opt/fermatai" if os.path.isdir("/opt/fermatai/.git") else "."
    try:
        cmd = ["git", "-C", repo, "diff", commit_or_branch]
        if file:
            ok_p, reason = _is_allowed_path(os.path.join(repo, file))
            if not ok_p:
                return {"error": f"Sandbox engeli: {reason}"}
            cmd.append("--")
            cmd.append(file)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, errors="replace")
        text = proc.stdout[:50000]
        masked, hits = _mask_secrets(text)
        await _audit(_caller_phone, "git_diff",
                     {"target": commit_or_branch, "file": file},
                     True, bytes_read=len(masked))
        return {
            "target": commit_or_branch,
            "file": file or None,
            "diff": masked,
            "secrets_masked": hits,
            "truncated": len(proc.stdout) > 50000,
        }
    except Exception as e:
        await _audit(_caller_phone, "git_diff", {}, False, error=str(e))
        return {"error": str(e)[:200]}


async def git_log(file: str = "", limit: int = 20,
                  _caller_phone: str = "") -> dict:
    """Git log — son N commit, file filter destekli."""
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali."}

    repo = "/opt/fermatai" if os.path.isdir("/opt/fermatai/.git") else "."
    limit = min(int(limit or 20), 100)
    try:
        cmd = ["git", "-C", repo, "log",
               f"--max-count={limit}",
               "--pretty=format:%H|%ai|%an|%s"]
        if file:
            ok_p, reason = _is_allowed_path(os.path.join(repo, file))
            if not ok_p:
                return {"error": f"Sandbox engeli: {reason}"}
            cmd.extend(["--", file])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        commits = []
        for line in proc.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "sha": parts[0][:10],
                    "date": parts[1],
                    "author": parts[2],
                    "subject": parts[3],
                })
        await _audit(_caller_phone, "git_log",
                     {"file": file, "limit": limit}, True, bytes_read=len(proc.stdout))
        return {"file": file or None, "commits": commits, "count": len(commits)}
    except Exception as e:
        return {"error": str(e)[:200]}


async def git_blame(file: str, line_no: int,
                    _caller_phone: str = "") -> dict:
    """Bir satirin son commit author + sha'i."""
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali."}

    repo = "/opt/fermatai" if os.path.isdir("/opt/fermatai/.git") else "."
    full = os.path.join(repo, file)
    ok_p, reason = _is_allowed_path(full)
    if not ok_p:
        return {"error": f"Sandbox engeli: {reason}"}

    line_no = max(1, int(line_no or 1))
    try:
        cmd = ["git", "-C", repo, "blame", "-L", f"{line_no},{line_no}",
               "--porcelain", file]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = proc.stdout
        m = re.search(r"^([0-9a-f]{40})", out, re.M)
        author_m = re.search(r"^author\s+(.+)$", out, re.M)
        time_m = re.search(r"^author-time\s+(\d+)$", out, re.M)
        summary_m = re.search(r"^summary\s+(.+)$", out, re.M)

        await _audit(_caller_phone, "git_blame",
                     {"file": file, "line": line_no}, True, bytes_read=len(out))
        return {
            "file": file,
            "line": line_no,
            "sha": (m.group(1)[:10] if m else None),
            "author": (author_m.group(1) if author_m else None),
            "timestamp": (int(time_m.group(1)) if time_m else None),
            "summary": (summary_m.group(1) if summary_m else None),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


async def search_atlas_history(category: str = "", limit: int = 20,
                                _caller_phone: str = "") -> dict:
    """Gecmis Atlas suggestion + observation kayitlarini ara.

    Bot brief yazarken "bu sorun daha once gozlendi mi" sorusunu
    cevaplayabilsin diye.
    """
    if not await _is_pipeline_active():
        return {"error": "Self-dev pipeline kapali."}

    limit = min(int(limit or 20), 100)
    where = "1=1"
    params: list = [limit]
    if category:
        where += " AND category = $2"
        params.append(category)
        sql_sug = f"""SELECT id, severity, category, title, status, created_at
                       FROM atlas_suggestions
                       WHERE {where}
                       ORDER BY created_at DESC LIMIT $1"""
        sql_obs = f"""SELECT id, severity, category, rationale, created_at
                       FROM atlas_observations
                       WHERE {where}
                       ORDER BY created_at DESC LIMIT $1"""
    else:
        sql_sug = """SELECT id, severity, category, title, status, created_at
                       FROM atlas_suggestions
                       ORDER BY created_at DESC LIMIT $1"""
        sql_obs = """SELECT id, severity, category, rationale, created_at
                       FROM atlas_observations
                       ORDER BY created_at DESC LIMIT $1"""

    try:
        from db_pool import db_fetch
        sugs = await db_fetch(sql_sug, *params)
        obs = await db_fetch(sql_obs, *params)
        await _audit(_caller_phone, "search_atlas_history",
                     {"category": category, "limit": limit}, True,
                     bytes_read=(len(sugs) + len(obs)) * 100)
        return {
            "category": category or "all",
            "suggestions": [dict(r) for r in sugs],
            "observations": [dict(r) for r in obs],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ─── KILL SWITCH KOMUTU (Neo) ───────────────────────────────────────────────

async def set_pipeline_active(active: bool, by_phone: str = "") -> dict:
    """Neo 'self dev ac/kapat' yazinca tetiklenir."""
    try:
        from db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO sistem_ayar (key, value, updated_at)
                   VALUES ('SELF_DEV_PIPELINE_ACTIVE', $1, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()""",
                "true" if active else "false",
            )
        invalidate_killswitch_cache()
        await _audit(by_phone, "set_pipeline_active",
                     {"active": active}, True, blocked_by="")
        return {
            "ok": True,
            "active": active,
            "message": "Self-dev pipeline ACIK ✅" if active else "Self-dev pipeline KAPALI ⛔",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        print(f"Pipeline active: {await _is_pipeline_active()}")
        print()

        # Test 1: read_file
        print("=== read_file test ===")
        r = await read_file("/opt/fermatai/eyotek_agent/conversation_memory.py", lines="1-30")
        if "error" in r:
            print(f"  Error: {r['error']}")
        else:
            print(f"  Path: {r['path']}")
            print(f"  Bytes: {r['bytes']}, Secrets masked: {r['secrets_masked']}")
            print(f"  Content (ilk 200 char): {r['content'][:200]}")
        print()

        # Test 2: secret block
        print("=== secret file engel ===")
        r2 = await read_file("/opt/fermatai/.env")
        print(f"  Result: {r2}")
        print()

        # Test 3: outside sandbox
        print("=== outside sandbox engel ===")
        r3 = await read_file("/etc/passwd")
        print(f"  Result: {r3}")
        print()

        # Test 4: grep
        print("=== grep_repo ===")
        r4 = await grep_repo("def get_student_context", file_type="py", limit=5)
        print(f"  Found {r4.get('count', 0)} matches")
        for m in (r4.get("matches") or [])[:3]:
            print(f"    {m['file']}:{m['line']} | {m['content'][:80]}")

    asyncio.run(_test())
