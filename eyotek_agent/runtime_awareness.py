"""
FermatAI — Runtime Self-Awareness
==================================
KALDIGIM.md'yi okur, son N oturumun özetini system prompt'a enjekte
edilecek formata dönüştürür. Bot "kendi güncelliğini" dinamik olarak bilir.

Manuel güncelleme YOK — sadece KALDIGIM.md güncellenir, bot otomatik farkında olur.
Cache: boot zamanında 1 kez okunur (~1ms), bridge restart gerekir.

Kullanım:
  from runtime_awareness import get_runtime_awareness
  txt = get_runtime_awareness()  # ~2-4K karakter, son 2 oturum özeti
"""
import re
from pathlib import Path
from datetime import datetime

# KALDIGIM.md proje kökünde
KALDIGIM_PATH = Path(__file__).parent.parent / "KALDIGIM.md"

# mtime-based cache — KALDIGIM.md guncellenince otomatik yenilenir
_CACHE: dict = {"mtime": 0.0, "block": ""}


def _extract_recent_sessions(content: str, max_sessions: int = 2) -> list[str]:
    """KALDIGIM.md'den son N oturum bölümünü parse et."""
    # ## <emoji> OTURUM XX ile başlayan bölümler
    sections = re.split(r'\n(?=## )', content)

    # OTURUM kelimesi geçen + başlığı ## olan bölümleri filtrele
    oturum_sections = []
    for s in sections:
        first_line = s.split('\n', 1)[0] if s else ''
        if 'OTURUM' in first_line.upper() or 'oturum' in first_line[:100]:
            oturum_sections.append(s)
        if len(oturum_sections) >= max_sessions:
            break

    return oturum_sections[:max_sessions]


def _clean_section(section: str, max_lines: int = 50) -> str:
    """Bölümü kısalt — ilk N satır, kod blokları ve long markdown'u temizle."""
    lines = section.split('\n')

    # Kod bloklarını atla (```...```)
    in_code = False
    cleaned = []
    for line in lines[:max_lines]:
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        # Çok uzun satırları kısalt
        if len(line) > 200:
            line = line[:200] + '...'
        cleaned.append(line)

    return '\n'.join(cleaned).rstrip()


def get_runtime_awareness(max_chars: int = 3500) -> str:
    """
    Son 2 oturumun özetini system prompt için hazırla.
    mtime-cached — KALDIGIM.md güncellenirse OTOMATİK yenilenir (restart gerekmez).
    """
    if not KALDIGIM_PATH.exists():
        return ""

    try:
        current_mtime = KALDIGIM_PATH.stat().st_mtime

        # Cache hit — dosya değişmedi
        if current_mtime == _CACHE["mtime"] and _CACHE["block"]:
            return _CACHE["block"]

        # Cache miss — yeniden oku
        content = KALDIGIM_PATH.read_text(encoding="utf-8")

        header_match = re.search(r'> \*\*Son güncelleme:\*\* ([^\n]+)', content)
        header = header_match.group(1) if header_match else ""

        bridge_match = re.search(r'> \*\*Bridge:\*\* ([^\n]+)', content)
        bridge = bridge_match.group(1) if bridge_match else ""

        sections = _extract_recent_sessions(content, max_sessions=2)

        if not sections:
            _CACHE["mtime"] = current_mtime
            _CACHE["block"] = ""
            return ""

        cleaned = [_clean_section(s, max_lines=45) for s in sections]

        parts = []
        if header:
            parts.append(f"📍 Son güncelleme: {header}")
        if bridge:
            parts.append(f"🔌 Bridge: {bridge}")
        parts.append("")
        parts.extend(cleaned)

        result = '\n'.join(parts)

        if len(result) > max_chars:
            result = result[:max_chars] + "\n\n[... devami KALDIGIM.md'de ...]"

        # Cache'i güncelle
        _CACHE["mtime"] = current_mtime
        _CACHE["block"] = result

        return result

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"runtime_awareness okuma hatasi: {e}")
        return ""


def refresh_cache():
    """Cache'i manuel temizle (test amaçlı, normalde mtime auto-invalidate eder)."""
    _CACHE["mtime"] = 0.0
    _CACHE["block"] = ""


def get_awareness_block() -> str:
    """
    System prompt'a eklenmek üzere bloğu hazırla — prefix/suffix ile.
    """
    awareness = get_runtime_awareness()
    if not awareness:
        return ""

    return (
        "\n🧠 GÜNCEL RUNTIME FARKINDALIĞI — Son oturumlarda ne değişti (dinamik, KALDIGIM.md'den):\n"
        "────────────────────────────────────────────────────────────────\n"
        f"{awareness}\n"
        "────────────────────────────────────────────────────────────────\n"
        "Bu bölüm HER bridge restart'ında KALDIGIM.md'den otomatik yenilenir.\n"
        "Neo sana 'son durum ne / ne değişti / yeni fix ne' diye sorduğunda yukarıdaki notları kullan.\n"
    )


if __name__ == "__main__":
    # CLI test
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("RUNTIME AWARENESS — KALDIGIM.md'den canli ozet")
    print("=" * 70)
    block = get_awareness_block()
    if block:
        print(block)
        print(f"\nBoyut: {len(block)} karakter ({len(block)//4} token ~)")
    else:
        print("[UYARI] KALDIGIM.md okunamadi veya OTURUM bolumu bulunamadi")
