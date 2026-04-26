"""
Modüler Prompt Composer (Oturum 25.18 — Faz 5 iskelet)
========================================================

Kullanım:
    from prompt_modules.composer import build_prompt
    prompt_text = build_prompt(["karakter", "kvkk_acl", "kurumsal"])

Şu an stub. Gerçek modüller (karakter.py, kvkk_acl.py vs.) yazılınca
build_prompt onları concatenate edecek.

Backward compat: hiç modül verilmezse mevcut SYSTEM_PROMPT döner.
"""
from __future__ import annotations
from typing import List, Optional


# Kayıtlı modül adları (gelecek extract için iskelet)
_AVAILABLE_MODULES = [
    "karakter",      # Karakter ruhu + üslup
    "kurumsal",      # Fermat kurum bilgileri
    "kvkk_acl",      # Yetki, KVKK, ACL kuralları
    "finans",        # Finans red kuralları
    "pedagoji",      # Pedagojik destek + şablon
    "scenario",      # Öğrenci/öğretmen senaryoları
    "atlas",         # Admin self-awareness
    "easter",        # Easter egg referansları
]


def list_available_modules() -> List[str]:
    """Kayıtlı modül adlarını dön."""
    return list(_AVAILABLE_MODULES)


def build_prompt(modules: Optional[List[str]] = None) -> str:
    """Verilen modüllerden prompt compose et.

    Args:
        modules: modül adları (örn ["karakter", "kvkk_acl"])
                 None → mevcut SYSTEM_PROMPT (backward compat)

    Returns:
        Compose edilmiş prompt string
    """
    if not modules:
        # Backward compat: mevcut SYSTEM_PROMPT
        try:
            from system_prompts import SYSTEM_PROMPT
            return SYSTEM_PROMPT
        except Exception:
            return ""

    # Gerçek modül loading (Faz 5'te aktif olacak)
    parts = []
    for m in modules:
        if m not in _AVAILABLE_MODULES:
            continue
        try:
            mod = __import__(f"prompt_modules.{m}", fromlist=[m])
            content = getattr(mod, "PROMPT_BLOCK", "")
            if content:
                parts.append(content)
        except ImportError:
            continue
        except Exception:
            continue

    if not parts:
        # Hiç modül yüklenmediyse → fallback FULL
        try:
            from system_prompts import SYSTEM_PROMPT
            return SYSTEM_PROMPT
        except Exception:
            return ""

    return "\n\n".join(parts)


# Tier → modül seti mapping (Faz 5'te aktif kullanım)
TIER_MODULES = {
    "light":  ["karakter", "kurumsal", "kvkk_acl"],
    "normal": ["karakter", "kurumsal", "kvkk_acl", "finans", "pedagoji"],
    "full":   _AVAILABLE_MODULES,  # hepsi
}


def build_prompt_for_tier(tier: str) -> str:
    """Tier'a göre uygun modül setinden prompt compose et."""
    modules = TIER_MODULES.get(tier, _AVAILABLE_MODULES)
    return build_prompt(modules)
