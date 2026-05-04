# -*- coding: utf-8 -*-
"""
Composer V3 — Modüler Prompt Compose (25.40z3 Faz 3)
======================================================

Mevcut SYSTEM_PROMPT'tan 3 büyük modül EXTRACT EDILDI:
- pedagoji_extended (52K char) — pazarlama, plan, yeni nesil, tutarlılık
- render_extended (25K char) — chart/3d/sim/compound/compton
- db_schema_extended (12K char) — students/exams + SQL pattern

Compose mantığı:
- BASE = SYSTEM_PROMPT - (3 modülün toplam içeriği) ~= persona + güvenlik + roller + KVKK + tools
- Modüller compose'a göre eklenir:
  - pedagoji: rol=ogrenci/rehber/admin VE intent=kavram/plan/analiz/duygu
  - render: kanal=web (whatsapp'ta gerek yok)
  - db_schema: rol=admin/mudur (SQL yazıyorsa)

CACHE_CONTROL HAZIRLIKLI:
build_prompt_v3() iki format döndürür:
  1. text: tek string (V2 ile uyumlu)
  2. blocks: list of {type, text, cache_control} → Anthropic API hierarchical cache
"""
from __future__ import annotations
from typing import Optional


# ─── Modül Yükleme Stratejisi ───────────────────────────────────────────────

def _should_load_pedagoji(role: str, intent: Optional[str]) -> bool:
    """Pedagoji bloğu (~39K char): rol + intent bazlı.

    25.40z3 LOOP1 fix: admin'de SADECE pedagoji-related intent'lerde yükle
    (admin'in sürekli pedagoji bloğu yüklemesine gerek yok — daha optimize)
    """
    role_l = (role or "").lower()
    if role_l in ("ogrenci", "rehber"):
        return True  # bu roller her zaman pedagoji ile çalışır
    if role_l in ("admin", "mudur", "ogretmen"):
        # Sadece pedagoji-related intent'lerde
        if intent in ("plan_yap", "kavram_aciklama", "ornek_iste", "cozum_iste",
                      "ozet_iste", "yontem_iste", "duygu_paylasim", "motivasyon_destek",
                      "test_olusturma", "soru_uret", "yeni_nesil_uret",
                      "konu_anlatim_uzun", "ornek_paket_uret"):
            return True
    return False


def _should_load_render(channel: str, intent: Optional[str]) -> bool:
    """Render bloğu (~25K char): sadece web kanalında ve render gerektirenlerde."""
    if channel != "web":
        return False
    # WhatsApp'ta render gereksiz (zaten _LOCAL_SYSTEM_WEB_ADDON'da)
    # Web'de bile sadece görsel intent'lerde gerekli
    if intent in ("selamlama", "veda", "tesekkur", "onay", "yetenek_sorgu", "meta_direktif"):
        return False  # bu intent'lerde render gerek yok
    return True


def _should_load_db_schema(role: str, intent: Optional[str]) -> bool:
    """DB schema bloğu (~12K char): sadece admin/mudur ve SQL gerektirenlerde."""
    role_l = (role or "").lower()
    if role_l not in ("admin", "mudur", "rehber"):
        return False
    # Sadece DB sorgusu gerektiren intent'lerde
    if intent in ("analiz_iste", "deneme_analiz", "plan_yap", "meta_direktif"):
        return True
    return False


# ─── BASE Çıkarma — SYSTEM_PROMPT'tan 3 modülü siler ────────────────────────

_BASE_CACHE: Optional[str] = None


def _clean_block_for_replace(block: str) -> str:
    """Modul block'undan replace oncesi safe-trim yapar.

    Extract scriptinde nadiren modul son satirina Python triple-quote
    kalintisi gomulmus olabilir (db_schema_extended vakasi). Bu artifact
    SYSTEM_PROMPT'ta YOK oldugu icin replace TAM ESLESMEZ ve modul BASE'de kalir
    (duplicate token). Burada safe-trim ile bu kalinti temizlenir.
    """
    import re
    # Sondaki triple-quote artifact'i temizle
    cleaned = re.sub(r'"""\s*$', '', block)
    return cleaned


def get_base_prompt() -> str:
    """SYSTEM_PROMPT - (pedagoji + render + db_schema) = BASE.

    BASE = persona + güvenlik + roller + KVKK + tools + intent rules
    Ortalama 75K char (155K - 80K).

    Cache: BASE statik, runtime değişmez — cache_control: ephemeral için ideal.

    25.40z3 production fix: replace TAM ESLESMEZSE (modul artifact'i nedeniyle)
    fuzzy fallback uygulanir - block sonundaki triple-quote trail temizlenir,
    sonra prefix eslesmesi denenir.
    """
    global _BASE_CACHE
    if _BASE_CACHE is not None:
        return _BASE_CACHE

    from system_prompts import SYSTEM_PROMPT
    from prompt_modules import pedagoji_extended, render_extended, db_schema_extended

    base = SYSTEM_PROMPT
    for mod_name, mod in [
        ("pedagoji", pedagoji_extended),
        ("render", render_extended),
        ("db_schema", db_schema_extended),
    ]:
        block = mod.PROMPT_BLOCK
        new_base = base.replace(block, "")
        if new_base == base:
            # Tam eşleşme başarısız → cleaned versiyon dene
            cleaned = _clean_block_for_replace(block)
            new_base = base.replace(cleaned, "")
            if new_base == base:
                # Hâlâ eşleşmedi → prefix-based replace (en uzun ortak prefix)
                # Block'un ilk 5K char'ı BASE'de varsa onu bulup, block sonuna
                # kadar olan alanı sil. Bu güvenlidir çünkü modül baş+son
                # marker'ları unique'tir.
                prefix_len = 5000
                if len(block) > prefix_len:
                    prefix = block[:prefix_len]
                    if prefix in base:
                        idx = base.index(prefix)
                        # Block'un orijinal uzunluğu kadar ilerleyerek sil
                        # (tolerance: ±100 char modül artifact için)
                        end_idx = idx + len(block)
                        # Tolerance: gerçek modül sınırı için son 200 char'a bak
                        end_search = base[end_idx-200:end_idx+200]
                        new_base = base[:idx] + base[end_idx:]
        base = new_base

    _BASE_CACHE = base
    return base


# ─── Ana Compose Fonksiyonu ─────────────────────────────────────────────────

def build_prompt_v3(
    role: str = "ogrenci",
    intent: Optional[str] = None,
    channel: str = "whatsapp",
    return_blocks: bool = False,
) -> tuple:
    """V3 prompt compose — modüler.

    Args:
        role: çağıranın rolü
        intent: tespit edilen intent (selamlama/kavram_aciklama/...)
        channel: 'whatsapp' veya 'web'
        return_blocks: True ise Anthropic API hierarchical block list döndürür
                       False ise concat string

    Returns:
        (prompt_or_blocks, info_dict)
        info_dict: {modules_loaded, total_size, base_size, ...}
    """
    base = get_base_prompt()

    # Modüller
    blocks_to_load = ["base"]
    extras = []

    if _should_load_pedagoji(role, intent):
        from prompt_modules import pedagoji_extended
        extras.append(("pedagoji", pedagoji_extended.PROMPT_BLOCK))
        blocks_to_load.append("pedagoji")

    if _should_load_render(channel, intent):
        from prompt_modules import render_extended
        extras.append(("render", render_extended.PROMPT_BLOCK))
        blocks_to_load.append("render")

    if _should_load_db_schema(role, intent):
        from prompt_modules import db_schema_extended
        extras.append(("db_schema", db_schema_extended.PROMPT_BLOCK))
        blocks_to_load.append("db_schema")

    info = {
        "modules_loaded": blocks_to_load,
        "base_size": len(base),
        "extras_size": sum(len(t) for _, t in extras),
        "total_size": len(base) + sum(len(t) for _, t in extras),
        "role": role,
        "intent": intent,
        "channel": channel,
    }

    if return_blocks:
        # Anthropic API hierarchical format
        # 1. BASE: cache_control ephemeral (statik, en uzun cache)
        # 2. EXTRAS: cache_control ephemeral (her modül için ayrı cache)
        api_blocks = [
            {
                "type": "text",
                "text": base,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        for name, text in extras:
            api_blocks.append({
                "type": "text",
                "text": text,
                "cache_control": {"type": "ephemeral"},
            })
        return api_blocks, info
    else:
        # Concat string (V2 ile uyumlu fallback)
        text = base + "".join(t for _, t in extras)
        return text, info


# ─── CLI Test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("Composer V3 — Modüler Prompt Test\n")
    base = get_base_prompt()
    print(f"BASE (statik): {len(base):,} char")
    print(f"  ↑ Cache_control ile bu blok cache'lenir (her zaman aynı)\n")

    test_cases = [
        ("ogrenci", "selamlama", "whatsapp"),
        ("ogrenci", "kavram_aciklama", "web"),
        ("ogrenci", "deneme_analiz", "whatsapp"),
        ("ogretmen", "selamlama", "whatsapp"),
        ("mudur", "analiz_iste", "whatsapp"),
        ("admin", "meta_direktif", "whatsapp"),
        ("admin", "kavram_aciklama", "web"),
    ]

    for role, intent, channel in test_cases:
        text, info = build_prompt_v3(role, intent, channel)
        modules = "+".join(info["modules_loaded"])
        print(f"  {role:10}/{intent:20}/{channel:10} → {info['total_size']:>7,} char  [{modules}]")

    print("\n--- Cache_control hierarchical (return_blocks=True) ---")
    blocks, info = build_prompt_v3("ogrenci", "kavram_aciklama", "web", return_blocks=True)
    for i, b in enumerate(blocks):
        print(f"  Block {i+1}: {len(b['text']):,} char (cache_control: {b['cache_control']['type']})")
