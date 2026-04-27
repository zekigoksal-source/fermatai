"""
Türkçe Mesaj Normalizasyonu (Oturum 25.21)
=============================================

Bot Neo ile konuşmasında tespit etti:
- "kisaca" → Groq 1.3sn ✅
- "kısaca" → Claude 12.9sn ❌
- "Damla'nın notu" / "damla nın notu" / "Damla notu" → 3 farklı route

Çözüm: Tüm pattern matching ÖNCESI mesajı normalize et.

Kural: keyword listesindeki ASCII Turkish-friendly varyantı yakalansın.
Bot davranışına ETKİ ETMEZ — sadece classifier seviyesinde normalize.
Bot kullanıcıya cevap verirken orijinal mesajı görür.
"""
from __future__ import annotations
import unicodedata
import re


# Türkçe → ASCII tablosu
_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ş": "s", "Ş": "s",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
    "â": "a", "Â": "a",
    "î": "i", "Î": "i",
    "û": "u", "Û": "u",
})


def tr_normalize(text: str) -> str:
    """Türkçe karakter + apostrof + boşluk normalize.

    "Damla'nın notu" → "damla nin notu"
    "kısaca anlat"   → "kisaca anlat"
    "Mahsum'un maaşı" → "mahsum un maasi"
    """
    if not text or not isinstance(text, str):
        return ""
    # Lowercase
    s = text.lower()
    # NFC formatına getir (combining characters)
    s = unicodedata.normalize("NFC", s)
    # Türkçe → ASCII
    s = s.translate(_TR_MAP)
    # Apostrof ve özel karakterleri boşluk yap
    s = re.sub(r"[''`´]", " ", s)
    # Yan yana boşluklar tek
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def tr_lower(text: str) -> str:
    """Türkçe lowercase (i/I/İ doğru — Python lower() bu işi yapamaz)."""
    if not text:
        return ""
    return text.replace("İ", "i").replace("I", "ı").lower()


def both_variants(keyword: str) -> tuple[str, str]:
    """Keyword'ün Türkçe + ASCII iki varyantını döner.

    'kısaca' → ('kısaca', 'kisaca')
    """
    return (tr_lower(keyword), tr_normalize(keyword))


def matches_normalized(text: str, keywords: list[str]) -> str | None:
    """Mesaj normalize edilip keyword listesinde aranır.

    Returns: eşleşen keyword veya None.
    """
    if not text or not keywords:
        return None
    norm = tr_normalize(text)
    for kw in keywords:
        kw_norm = tr_normalize(kw)
        if kw_norm and kw_norm in norm:
            return kw
    return None
