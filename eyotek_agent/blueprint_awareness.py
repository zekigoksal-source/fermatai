"""
BLUEPRINT Awareness — Oturum 25.29
====================================

Bot + Atlas + KALDIGIM aynı mimari bakış açısı paylaşsın diye BLUEPRINT.md'i
canlı parse eder, özet çıkarır, section bazlı tool sunar.

Mimari (KALDIGIM ile koordineli):
  - KALDIGIM.md  → "ne YAPILDI" (oturum bazlı zaman çizelgesi)
  - BLUEPRINT.md → "ne VAR / nasıl ÇALIŞIYOR" (mimari kapasite)
  - Atlas        → "neyi GÖZLEMLEDIM, ne ÖNERIYORUM" (canlı self-report)

Bu üçü birbiriyle TUTARLI olmalı:
  - KALDIGIM oturum sonu güncellenir → BLUEPRINT teknik tablo eşit güncellenir
  - Atlas öneri verirken BLUEPRINT'e bakar — "bu zaten mimari karardı" tespit eder
  - Bot mimari sorulduğunda BLUEPRINT executive summary'i hatırlar, detay için
    get_blueprint_section() çağırır.

API:
  get_blueprint_summary()        → kompakt mimari ozeti (her mesajda inject)
  get_blueprint_section(name)    → tam section icerigi (Claude tool, on-demand)
  list_blueprint_sections()      → tum baslik listesi
  search_blueprint(query)        → keyword bazli ilgili section'lari bul
"""
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


_BLUEPRINT_PATH = Path(__file__).resolve().parent.parent / "BLUEPRINT.md"


def _read_blueprint() -> str:
    try:
        return _BLUEPRINT_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _modified_at() -> str:
    try:
        ts = _BLUEPRINT_PATH.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "?"


def _parse_sections() -> list[dict]:
    """BLUEPRINT.md'i ## N. başlık bazlı parse et."""
    text = _read_blueprint()
    if not text:
        return []
    pattern = re.compile(
        r"(##\s+(\d+)\.\s+(.+?))(?=\n##\s+\d+\.|\Z)",
        re.DOTALL,
    )
    sections = []
    for m in pattern.finditer(text):
        full_block = m.group(1).strip()
        num = m.group(2)
        title = m.group(3).split("\n", 1)[0].strip()
        sections.append({
            "num": int(num),
            "title": title,
            "content": full_block,
            "char_count": len(full_block),
        })
    return sections


# ─── ANA API ─────────────────────────────────────────────────────────────────

def get_blueprint_summary(max_chars: int = 1800) -> str:
    """Kompakt mimari özet — her mesajda dynamic_context'e inject edilebilir.

    İçerik:
      - Belge tarihi + son güncellenme
      - Executive Summary'den 8-10 satır kapasite tablosu
      - Tum section başlıkları (numerik liste)
      - "Detay için: get_blueprint_section(num) çağır" notu
    """
    text = _read_blueprint()
    if not text:
        return ""

    # Header (ilk 6 satır)
    header_lines = text.split("\n", 12)[:6]
    header_block = "\n".join(line for line in header_lines if line.strip())[:600]

    sections = _parse_sections()
    if not sections:
        return ""

    # Section listesi
    listing_lines = []
    for s in sections[:18]:
        listing_lines.append(f"  {s['num']}. {s['title'][:70]}")
    sections_listing = "\n".join(listing_lines)

    summary = (
        f"🏛️ MIMARI BLUEPRINT FARKINDALIK (BLUEPRINT.md, "
        f"son güncelleme {_modified_at()}):\n"
        f"────────────────────────────────────────────────\n"
        f"{header_block}\n\n"
        f"📋 BÖLÜMLER ({len(sections)} adet):\n"
        f"{sections_listing}\n\n"
        f"💡 Detay icin tool kullan: get_blueprint_section(num veya baslik)\n"
        f"   Ornek: 'LLM routing nasil calisir?' → get_blueprint_section(3)\n"
        f"────────────────────────────────────────────────"
    )

    if len(summary) > max_chars:
        summary = summary[:max_chars] + "\n[... ozet kesildi]"
    return summary


def get_blueprint_section(identifier) -> Optional[dict]:
    """Belirli bir section'ı tam haliyle döndür.

    Args:
        identifier: int (section num) veya str (başlık keyword)

    Returns:
        {num, title, content} veya None
    """
    sections = _parse_sections()
    if not sections:
        return None

    # Numeric match
    if isinstance(identifier, int):
        for s in sections:
            if s["num"] == identifier:
                return s
        return None

    # String match (case-insensitive keyword)
    if isinstance(identifier, str):
        ident_low = identifier.lower().strip()
        # Tam başlık match
        for s in sections:
            if ident_low == s["title"].lower():
                return s
        # Keyword in title
        for s in sections:
            if ident_low in s["title"].lower():
                return s
        # Keyword in content
        for s in sections:
            if ident_low in s["content"].lower():
                return s
    return None


def list_blueprint_sections() -> list[dict]:
    """Tüm bölümlerin başlık listesi."""
    sections = _parse_sections()
    return [
        {"num": s["num"], "title": s["title"], "char_count": s["char_count"]}
        for s in sections
    ]


def search_blueprint(query: str, max_results: int = 5) -> list[dict]:
    """BLUEPRINT içinde keyword arama — Atlas/Bot mimari kararı sorgulamak için.

    Returns: [{num, title, snippet, hit_count}, ...]
    """
    if not query or len(query) < 2:
        return []
    sections = _parse_sections()
    query_low = query.lower()
    hits = []
    for s in sections:
        content_low = s["content"].lower()
        count = content_low.count(query_low)
        if count == 0:
            continue
        # Snippet — query etrafında 200 char
        idx = content_low.find(query_low)
        start = max(0, idx - 100)
        end = min(len(s["content"]), idx + 200)
        snippet = s["content"][start:end].replace("\n", " ")
        hits.append({
            "num": s["num"],
            "title": s["title"],
            "snippet": "..." + snippet + "...",
            "hit_count": count,
        })
    hits.sort(key=lambda h: h["hit_count"], reverse=True)
    return hits[:max_results]


def get_architecture_decision(topic: str) -> Optional[dict]:
    """Section 17 'Önemli Mimari Kararlar' içinde topic ile ilgili karar var mı?

    Atlas advisor için kritik: yeni öneri vermeden önce kontrol etmeli.
    """
    sections = _parse_sections()
    decisions_section = None
    for s in sections:
        if "mimari karar" in s["title"].lower() or s["num"] == 17:
            decisions_section = s
            break
    if not decisions_section:
        return None

    topic_low = topic.lower()
    content = decisions_section["content"]
    if topic_low in content.lower():
        # Ilgili paragrafi bul
        idx = content.lower().find(topic_low)
        start = max(0, idx - 200)
        end = min(len(content), idx + 500)
        return {
            "found": True,
            "topic": topic,
            "decision_excerpt": content[start:end],
        }
    return {"found": False, "topic": topic}


# ─── CLI test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("BLUEPRINT SUMMARY")
    print("=" * 60)
    print(get_blueprint_summary())
    print()
    print("=" * 60)
    print("SECTION LISTING")
    print("=" * 60)
    for s in list_blueprint_sections():
        print(f"  {s['num']}. {s['title']} ({s['char_count']} char)")
    print()
    print("=" * 60)
    print("SEARCH 'Cerebras'")
    print("=" * 60)
    for h in search_blueprint("Cerebras"):
        print(f"  [#{h['num']}] {h['title']} (hit={h['hit_count']})")
        print(f"    {h['snippet'][:200]}")
        print()
