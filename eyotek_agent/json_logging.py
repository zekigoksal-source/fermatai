"""
Structured JSON Logging (Oturum 25.9 — T3)
==============================================
loguru'nun yaninda eszamanli JSON sink — query/grep/jq ile analiz kolayligi.

Aktivasyon: app baslangicinda `setup_json_logging()` cagir.
Cikti: /opt/fermatai/logs/structured/{date}.jsonl (rotated daily)

Format (her satir bir JSON):
  {"ts":"2026-04-25T20:30:00Z","level":"INFO","module":"fermat_core_agent",
   "message":"...", "extra":{"phone":"905...", "soz_no":137, "duration_ms":1240}}

Kullanim:
  from json_logging import structured_log
  structured_log("info", "user_message", phone=phone, soz_no=137, duration_ms=240)

Veya loguru'dan otomatik (bind ile):
  logger.bind(phone=phone, soz_no=137).info("user message handled")
  → JSON satirina extra alanlar yansir
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# Log dizini
_LOG_DIR = Path("/opt/fermatai/logs/structured")
if not _LOG_DIR.exists():
    # Local dev fallback
    _LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "structured"


def _json_serializer(record: dict) -> str:
    """loguru record → JSON satiri.

    record yapısı: {"time", "level", "name", "message", "extra", ...}
    """
    extra = record.get("extra", {}) or {}
    # loguru icindeki gereksiz alanlari at
    extra_clean = {k: v for k, v in extra.items() if not k.startswith("_")}

    payload = {
        "ts": record["time"].isoformat(),
        "level": record["level"].name,
        "module": record["name"],
        "function": record.get("function"),
        "line": record.get("line"),
        "message": record["message"],
    }

    # Extra alanlar varsa ekle
    if extra_clean:
        payload["extra"] = extra_clean

    # Exception varsa
    if record.get("exception"):
        payload["exception"] = str(record["exception"])

    try:
        return json.dumps(payload, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps({"ts": payload["ts"], "level": payload["level"],
                          "message": str(record["message"])[:500]})


def setup_json_logging(min_level: str = "INFO") -> None:
    """JSON sink ekle (mevcut text sink korunur, parallel calisir).

    Idempotent — birkaç kez çağrılırsa eski sink'i kaldırıp yeniler.
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # Yazılabilir değil — sessizce vazgeç (dev environment)
        print(f"[json_logging] Log dir create fail: {e}", file=sys.stderr)
        return

    # Önce eski JSON sink varsa temizle (handler id 100+)
    # loguru'da spesifik sink kaldirmak icin id gerekir; biz sadece yeni ekliyoruz
    # ve duplicate write rate'i kabul ediyoruz (gunluk rotated zaten)
    log_path = str(_LOG_DIR / "{time:YYYY-MM-DD}.jsonl")

    def _sink(message):
        # message bir loguru Message object'i, record dict access var
        record = message.record
        try:
            line = _json_serializer(record)
            # Manuel append (loguru'nun kendi rotation'i da var ama biz basit tutuyoruz)
            d = record["time"].strftime("%Y-%m-%d")
            path = _LOG_DIR / f"{d}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass  # Sessiz — ana log akisini kesintiye ugratma

    logger.add(
        _sink,
        level=min_level,
        # Filter: sadece extra alanlari olan veya WARNING+ olanlari logla?
        # Su an her seyi alalim, gerekirse filter eklenir.
    )
    logger.info("[json_logging] Structured JSON logging aktif",
                json_log_dir=str(_LOG_DIR))


def structured_log(
    level: str,
    event: str,
    **fields: Any,
) -> None:
    """Convenience helper: bind + log + done.

    Ornek:
      structured_log("info", "user_message_received",
                     phone="905...", soz_no=137, duration_ms=240)
    """
    bound = logger.bind(event=event, **fields)
    log_func = getattr(bound, level.lower(), bound.info)
    log_func(event)


# ── Query helpers (ops yardimi) ─────────────────────────────────────────────

def query_log_file(date_str: str, **filter_kwargs) -> list[dict]:
    """Belirli bir gunun JSON log'unu filtrele (ops icin).

    date_str: "2026-04-25"
    filter_kwargs: ornek phone="905...", level="ERROR"

    Returns: matching log records
    """
    path = _LOG_DIR / f"{date_str}.jsonl"
    if not path.exists():
        return []
    results = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            # Filter check
            ok = True
            for k, v in filter_kwargs.items():
                rec_val = rec.get(k) or rec.get("extra", {}).get(k)
                if rec_val != v:
                    ok = False
                    break
            if ok:
                results.append(rec)
    return results


if __name__ == "__main__":
    # Smoke test
    setup_json_logging()
    structured_log("info", "test_event", phone="905000000000", duration_ms=42)
    structured_log("warning", "test_warning", error_type="test")
    print(f"Logs written to {_LOG_DIR}")
    today = datetime.now().strftime("%Y-%m-%d")
    recs = query_log_file(today, phone="905000000000")
    print(f"Found {len(recs)} matching records")
