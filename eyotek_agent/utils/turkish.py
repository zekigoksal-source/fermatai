"""
Turkce Karakter Yardimcilari — Merkezi Modul (Oturum 22.1d)
============================================================

Duplicate bulundu: fast_responses.py, conversation_viewer.py, fermat_core_agent.py
Hepsi ayni _tr_lower, _tr_upper, _tr_title fonksiyonlarini yeniden yazmisti.
Bu modul tek kaynak. Bug fix burada yapilir, herkese yayilir.

Kullanim:
    from utils.turkish import tr_lower, tr_upper, tr_title, tr_fold

    tr_lower("İSTANBUL")  → "istanbul"
    tr_upper("istanbul")  → "İSTANBUL"
    tr_title("ayşe yılmaz")  → "Ayşe Yılmaz"
    tr_fold("Şeyma")  → "seyma"  (arama icin)
"""

# Turkce kucuk harfe cevirme haritasi
_TR_LOWER = str.maketrans(
    "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ",
    "abcçdefgğhıijklmnoöprsştuüvyz",
)

# Turkce buyuk harfe cevirme haritasi
_TR_UPPER = str.maketrans(
    "abcçdefgğhıijklmnoöprsştuüvyz",
    "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ",
)

# ASCII fold — arama/hash/normalize icin (ıİşŞ vs dikkate almaz)
_TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "i": "i",
    "ş": "s", "Ş": "s", "s": "s", "S": "s",
    "ğ": "g", "Ğ": "g", "g": "g", "G": "g",
    "ü": "u", "Ü": "u", "u": "u", "U": "u",
    "ö": "o", "Ö": "o", "o": "o", "O": "o",
    "ç": "c", "Ç": "c", "c": "c", "C": "c",
})


def tr_lower(s: str) -> str:
    """Turkce kucuk harf — I→ı, İ→i."""
    if not s:
        return s
    return s.translate(_TR_LOWER).lower()


def tr_upper(s: str) -> str:
    """Turkce buyuk harf — i→İ, ı→I."""
    if not s:
        return s
    return s.translate(_TR_UPPER).upper()


def tr_title(s: str) -> str:
    """'ayşe yılmaz' → 'Ayşe Yılmaz' (her kelimenin ilk harfi buyuk)."""
    if not s:
        return s
    parts = []
    for word in s.split():
        if not word:
            continue
        first = word[0].translate(_TR_UPPER).upper() if word[0].lower() != word[0].upper() else word[0]
        # Turkce cevirme ilk harfte
        first = word[0].translate(_TR_UPPER) if word[0] in "abcçdefgğhıijklmnoöprsştuüvyzABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ" else word[0]
        rest = word[1:].translate(_TR_LOWER).lower() if len(word) > 1 else ""
        parts.append(first.upper() + rest)
    return " ".join(parts)


def tr_fold(s: str) -> str:
    """ASCII fold — 'Şeyma' → 'seyma' (arama/hash icin)."""
    if not s:
        return s
    return s.translate(_TR_FOLD).lower()


def tr_eq(a: str, b: str) -> bool:
    """Iki string Turkce farklarina duyarsiz esit mi? ('Ayşe' == 'ayse')."""
    return tr_fold(a or "") == tr_fold(b or "")


def tr_contains(haystack: str, needle: str) -> bool:
    """Turkce duyarsiz substring check."""
    return tr_fold(needle or "") in tr_fold(haystack or "")
