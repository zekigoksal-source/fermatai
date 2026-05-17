"""
ATLAS Code Awareness — Oturum 25.46+ (Neo 18 May)
==================================================

Atlas-2'nin "kod tabanını bilmediği için mevcut olanı tekrar tanımlama"
sorununu çözer.

Akış:
  1. extract_existing_patterns() — kritik dosyaları okur, fonksiyon/constant/
     prompt bölüm başlıklarını çıkarır (cache 1 saat)
  2. grep_codebase(keywords) — anahtar kelimeleri ilgili dosyalarda arar
  3. build_codebase_context(problems) — problem türlerinden anahtar kelime
     türetir, grep yapar, Atlas LLM prompt'a inject edilecek "MEVCUT KOD"
     bloğu üretir
  4. verify_suggestion_novelty(suggestion) — INSERT öncesi: önerinin
     suggested_change alanındaki anahtar kelimeler 3+ dosyada zaten varsa
     "ALREADY_EXISTS" döner → öneri filtrelenir veya severity düşürülür

Neo direktif (18 May): "Atlas boş öneri yapmasın, kod tabanını okuyup
mevcut olanı tekrar tanımlamasın. Self-awareness AI ajanlarında kritik."
"""
from __future__ import annotations
import asyncio
import re
import time
from pathlib import Path
from typing import Iterable

from loguru import logger


# ── KRITIK DOSYALAR — Atlas önerilerinin %95'i bunlara dokunur ───────────
# Indexing maliyeti dengeleme: küçük (<500KB) ve sık değişen dosyalar.
EYOTEK_AGENT_ROOT = Path(__file__).resolve().parent.parent

CRITICAL_FILES = [
    "system_prompts.py",
    "fast_responses.py",
    "conversation_flow.py",
    "conversation_memory.py",
    "fermat_core_agent.py",
    "llm_router.py",
    "sentiment_tracker.py",
    "context_engine.py",
    "intent_parser.py",
    "tool_definitions.py",
    "role_access.py",
    "tercih_robotu.py",
    "atlas/observer.py",
    "atlas/advisor.py",
    "prompt_optimizer.py",
]


# ── ANAHTAR KELIME — PROBLEM TIPI MAPPING ────────────────────────────────
# Bir problem türü tespit edildiğinde, bot'un mevcut kodda neyi kontrol
# etmesi gerektiğini söyler. Atlas LLM'nin "context-aware response yok"
# demesinden önce, gerçekten context-aware response var mı diye bakar.
PROBLEM_KEYWORDS = {
    "frustration":          ["frustration", "escalation", "yanlis", "anlamadi"],
    "missed_intent":        ["intent_parser", "intent", "fast_response", "long_intent"],
    "repeated_response":    ["_PENDING_FOLLOWUP", "_PENDING_SPLIT", "deduplication"],
    "context_loss":         ["conversation_memory", "build_context_prompt", "_CONTEXT_CACHE"],
    "stale_data":           ["last_sync", "data_fetched_at", "STALE_DATA"],
    "hallucination":        ["HALUSINASYON", "uydurma", "ASLA", "tool_yoksa"],
    "personalization":      ["caller_name", "get_caller_profile", "isimle hitap"],
    "split_message":        ["_PENDING_SPLIT", "split_continuation", "auto continuation"],
    "tool_misuse":          ["TOOL_DISPATCH", "tool_use", "tool_executor"],
    "routing":              ["chat_cerebras_with_tools", "_CLOUD_KEYWORDS", "SAFE_GROQ_TOOLS"],
    "rate_limit":           ["rate_limit", "_check_rate_limit", "TPM"],
    "token_efficiency":     ["cache_control", "prompt_caching", "SYSTEM_PROMPT_BASE"],
}


# ── CACHE — Kod tarama maliyetini azalt (1 saatlik TTL) ──────────────────
_PATTERN_CACHE: dict[str, dict] = {}
_CACHE_TTL_SEC = 3600  # 1 saat


def _cache_get(key: str):
    entry = _PATTERN_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL_SEC:
        return entry["value"]
    return None


def _cache_set(key: str, value):
    _PATTERN_CACHE[key] = {"value": value, "ts": time.time()}


# ── 1. extract_existing_patterns: dosya başlık + fonksiyon listesi ───────

def extract_existing_patterns(file_path: str) -> dict:
    """Bir Python dosyasından üst-seviye pattern özeti çıkar.

    Döner: {
      "functions": [list of def names],
      "constants": [list of UPPER_SNAKE constant names],
      "section_headers": [list of "════ ... ════" başlıkları],
      "size_kb": int,
    }
    """
    cache_key = f"patterns::{file_path}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    full = EYOTEK_AGENT_ROOT / file_path
    if not full.exists():
        return {"functions": [], "constants": [], "section_headers": [], "size_kb": 0}

    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"[code_awareness] read fail {file_path}: {e}")
        return {"functions": [], "constants": [], "section_headers": [], "size_kb": 0}

    # Fonksiyon adları (sync + async)
    functions = re.findall(r"^(?:async\s+)?def\s+(\w+)\s*\(", text, re.MULTILINE)

    # UPPER_SNAKE constants (en az 3 char, _ veya BÜYÜK harf)
    constants = re.findall(r"^([A-Z][A-Z0-9_]{2,})\s*=", text, re.MULTILINE)

    # Prompt bölüm başlıkları ("══════", "🚨 BAŞLIK ══════" gibi)
    section_headers = re.findall(
        r"(?:[═]+|[#=]{3,})\s*([🚨🔴🟢🎯🆕🔧⚠][\s\S]{3,80}?)(?:[═]+|[#=]{3,}|\n)",
        text,
    )
    # Temizle
    section_headers = [h.strip()[:80] for h in section_headers if h.strip()]

    result = {
        "functions": list(set(functions))[:100],
        "constants": list(set(constants))[:50],
        "section_headers": section_headers[:30],
        "size_kb": len(text) // 1024,
    }
    _cache_set(cache_key, result)
    return result


# ── 2. grep_codebase: anahtar kelime arama ───────────────────────────────

def grep_codebase(
    keywords: Iterable[str],
    files: Iterable[str] | None = None,
    case_sensitive: bool = False,
) -> dict[str, list[tuple[int, str]]]:
    """Anahtar kelimeleri kritik dosyalarda ara.

    Döner: {
      "file_path": [(line_num, line_content), ...]
    }
    Eşleşme yoksa o dosya dict'te yok.
    """
    if not keywords:
        return {}

    target_files = list(files) if files else CRITICAL_FILES
    flags = 0 if case_sensitive else re.IGNORECASE
    patterns = [re.compile(re.escape(k), flags) for k in keywords if k]

    matches: dict[str, list[tuple[int, str]]] = {}
    for fp in target_files:
        full = EYOTEK_AGENT_ROOT / fp
        if not full.exists():
            continue
        try:
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        file_matches = []
        for i, line in enumerate(lines, 1):
            if any(p.search(line) for p in patterns):
                file_matches.append((i, line.strip()[:120]))
                if len(file_matches) >= 5:  # Per file max 5 örnek
                    break
        if file_matches:
            matches[fp] = file_matches
    return matches


# ── 3. build_codebase_context: Atlas LLM prompt'a inject edilecek blok ───

def build_codebase_context(problems: list[dict]) -> str:
    """Problem örneklerinden anahtar kelime türet, grep yap, LLM'e
    enjekte edilecek "MEVCUT KOD CONTEXT" bloğu üret.

    Bu blok Atlas LLM'in "X mekanizması yok, ekle" demesini engeller —
    önce mevcut olanı görsün, ona göre öneri üretsin (extension veya
    farklı domain).
    """
    if not problems:
        return ""

    # Problem tiplerinden anahtar kelime havuzu çıkar
    keyword_pool = set()
    for p in problems:
        ptype = p.get("type", "")
        keyword_pool.update(PROBLEM_KEYWORDS.get(ptype, []))

    if not keyword_pool:
        return ""

    # Grep yap
    grep_results = grep_codebase(keyword_pool)
    if not grep_results:
        return ""

    # LLM-okunabilir özet
    lines = [
        "",
        "📋 MEVCUT KOD CONTEXT (Atlas-2 yeni öneri üretmeden ÖNCE oku):",
        "Bu dosyalarda zaten ilgili mekanizmalar tanımlı. Tekrar tanımlama:",
        "",
    ]
    for fp, hits in list(grep_results.items())[:10]:
        lines.append(f"  📄 {fp}: {len(hits)} eşleşme")
        for ln, snippet in hits[:3]:
            lines.append(f"     L{ln}: {snippet[:100]}")
        lines.append("")

    lines.append(
        "KURAL: Üretilen öneride yukarıdaki dosyalardaki mevcut mekanizmayı "
        "GÖRMEZDEN GELME. Eğer 'context-aware response ekle', 'frustration "
        "escalation ekle', 'split message yönet' gibi öneriler yukarıdaki "
        "kodda zaten mevcutsa, öneri YERINE 'mevcut mekanizmayı şu sebeple "
        "iyileştir' formatında yaz. Mevcut yok ise yeni öneri tamam."
    )
    lines.append("")
    return "\n".join(lines)


# ── 4. verify_suggestion_novelty: INSERT öncesi grep doğrulama ───────────

def verify_suggestion_novelty(suggestion: dict) -> dict:
    """Atlas LLM'in ürettiği öneriyi codebase'e karşı doğrula.

    Args:
      suggestion: {title, suggested_change, affected_pattern, ...}

    Döner: {
      "is_novel": bool,
      "matched_files": [filepath, ...],
      "match_count": int,
      "verdict": "novel" | "likely_exists" | "definitely_exists",
      "severity_downgrade": str | None,  # "low" gibi
      "note": str,
    }
    """
    text = " ".join([
        suggestion.get("title", ""),
        suggestion.get("suggested_change", ""),
        suggestion.get("affected_pattern", ""),
    ]).lower()

    # Anahtar kelime tahmini (3+ harf, stop word olmayan)
    stop = {
        "icin", "bir", "olan", "olur", "olsa", "gibi", "yada", "veya", "ile",
        "fast", "user", "bot", "ama", "ise", "her", "tum", "bos", "yeni",
        "kullanici", "kullanicilari", "kullanicilarin", "yanit", "yaniti",
        "yanitlar", "mesaj", "mesaji", "mesajlar", "mesajlari", "system",
        "prompt", "atlas", "test", "ornek", "ornekleri", "olma", "olmaz",
        "olabilir", "kontrol", "ekle", "ekleme", "eklenmeli", "uygulan",
        "uygulanmali", "ozelinde", "ozelliği", "ozelligi", "duzelt", "duzeltme",
    }
    raw_words = re.findall(r"\b[a-zçğıöşü_]{4,}\b", text)
    keywords = [w for w in set(raw_words) if w not in stop][:8]

    if not keywords:
        return {
            "is_novel": True,
            "matched_files": [],
            "match_count": 0,
            "verdict": "novel",
            "severity_downgrade": None,
            "note": "Anahtar kelime çıkarılamadı, novelty doğrulanamadı.",
        }

    grep_results = grep_codebase(keywords)
    matched_files = list(grep_results.keys())
    total_matches = sum(len(hits) for hits in grep_results.values())

    # Karar matrisi
    if len(matched_files) >= 4 and total_matches >= 10:
        return {
            "is_novel": False,
            "matched_files": matched_files,
            "match_count": total_matches,
            "verdict": "definitely_exists",
            "severity_downgrade": "low",
            "note": (
                f"Öneri konseptindeki anahtar kelimeler {len(matched_files)} kritik "
                f"dosyada {total_matches} kez geçiyor — büyük olasılıkla mevcut. "
                "Severity 'low'a düşürüldü, Neo manuel review yapsın."
            ),
        }
    elif len(matched_files) >= 2 and total_matches >= 5:
        return {
            "is_novel": False,
            "matched_files": matched_files,
            "match_count": total_matches,
            "verdict": "likely_exists",
            "severity_downgrade": None,
            "note": (
                f"Anahtar kelimeler {len(matched_files)} dosyada {total_matches} kez "
                "geçiyor — kısmen mevcut olabilir. Öneri SAKLANDI ama Neo'ya "
                "'kontrol et' uyarısı eklendi."
            ),
        }
    else:
        return {
            "is_novel": True,
            "matched_files": matched_files,
            "match_count": total_matches,
            "verdict": "novel",
            "severity_downgrade": None,
            "note": "Codebase'de eşleşme zayıf — büyük olasılıkla yeni öneri.",
        }


# ── 5. get_codebase_summary: günlük rapor için ───────────────────────────

def get_codebase_summary() -> dict:
    """Tüm kritik dosyaların pattern özetini topla — debug + rapor için."""
    summary = {}
    total_size_kb = 0
    total_functions = 0
    for fp in CRITICAL_FILES:
        patterns = extract_existing_patterns(fp)
        summary[fp] = {
            "function_count": len(patterns["functions"]),
            "constant_count": len(patterns["constants"]),
            "section_count": len(patterns["section_headers"]),
            "size_kb": patterns["size_kb"],
        }
        total_size_kb += patterns["size_kb"]
        total_functions += len(patterns["functions"])
    summary["_totals"] = {
        "total_size_kb": total_size_kb,
        "total_functions": total_functions,
        "indexed_files": len(CRITICAL_FILES),
    }
    return summary


if __name__ == "__main__":
    # Quick test
    import json
    print("=== Codebase Summary ===")
    print(json.dumps(get_codebase_summary(), indent=2))
    print("\n=== Grep test: 'frustration' ===")
    print(json.dumps(grep_codebase(["frustration"]), indent=2, default=str))
    print("\n=== Suggestion verify test ===")
    test_sugg = {
        "title": "Sabit mesajlarda bağlama duyarlı yanıt eksikliği",
        "suggested_change": "Sabit mesajlar gönderilmeden önce kullanıcı geçmiş bağlamı kontrol edilmeli.",
        "affected_pattern": "Tekrarlanan sabit mesaj patternleri",
    }
    print(json.dumps(verify_suggestion_novelty(test_sugg), indent=2, ensure_ascii=False))
