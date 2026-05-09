"""Yayinevi katalogu — TYT/AYT deneme yayinevlerinin merkezi listesi.

Olusturulus: Oturum 25.42 (9 May 2026, Mehmet Karpuz "0 pozitif" parse hatasi).
Sebep: Bot "0 pozitif" / "sifir pozitif" mesajini "0 sayisi pozitif midir" matematik
sorusu sandi (4 kere). Asil mesaj: Sifir Pozitif Yayinevi denemesi.

Kullanim:
    from yayinevi_katalog import detect_publisher, normalize_publisher
    pub = detect_publisher("0 pozitif yayini 65 net")  # → "Sifir Pozitif"
    pub = detect_publisher("apotemide 70 net")          # → "Apotemi"
    pub = detect_publisher("3d tyt-3 80 net")           # → "3D"
"""
from __future__ import annotations
import re
from typing import Optional


# Kanonik isim → varyantlar (lower-case, accent-fold edilmis)
# Varyantlar regex pattern olarak yazilir; "\b" word boundary otomatik eklenir
PUBLISHERS: dict[str, list[str]] = {
    # KRITIK: "0 pozitif" / "sifir pozitif" — math sorusu DEGIL, yayinevi adi
    "Sifir Pozitif": [
        r"s[iı]f[iı]r\s*pozitif",
        r"\b0\s*pozitif",        # "0 pozitif", "0pozitif"
        r"sifirpozitif",
        r"pozitif\s*yay[iı]n",   # "Pozitif Yayinlari" da bu kategoriye girer
    ],
    "Apotemi": [
        r"apotem[iı]",            # apotemide, apotemi'de, apotemi'nin
        r"apotemy",               # yazim hatasi
    ],
    "Palme": [
        r"palme",
    ],
    "3D": [
        r"\b3d\s*(tg|tyt|ayt|deneme|sinav|s[iı]nav|yay[iı]n)",
        r"\b3d\s+\d+\s*net",       # "3d 70 net"
        r"3\s*d\s*yay[iı]n",
    ],
    "Bilgi Sarmal": [
        r"bilgi\s*sarmal",
        r"sarmal\s*tyt",
        r"sarmal\s*ayt",
    ],
    "Yayin Denizi": [
        r"yay[iı]n\s*deniz",
        r"deniz\s*yay[iı]n",
    ],
    "UcDortBes": [
        r"u[cç]\s*d[oö]rt\s*be[sş]",
        r"345\s*(yay|tyt|ayt|deneme)",
        r"udb",                    # kisaltma
    ],
    "Limit": [
        r"limit\s*(yay|deneme|tyt|ayt|sinav|s[iı]nav)",
        r"limit\s+\d+\s*net",
    ],
    "Esen": [
        r"esen\s*(yay|deneme|tyt|ayt|sinav|s[iı]nav)",
        r"esen\s+\d+\s*net",
    ],
    "Cap": [
        r"\bcap\s*(yay|deneme|tyt|ayt|sinav|s[iı]nav)",
        r"\bcap\s+\d+\s*net",
        r"cap\s*denem",
    ],
    "Karekok": [
        r"karek[oö]k",
    ],
    "Tonguc": [
        r"tongu[cç]",
        r"tongucla",
    ],
    "Acil": [
        r"acil\s*(yay|deneme|tyt|ayt|s[iı]nav)",
        r"i[sş]ler\s*acil",         # "Isler Acil" sinif denemeleri
    ],
    "Isler": [
        r"\bi[sş]ler\b",
    ],
    "OSYM Direkt": [
        r"o?sym\s*direkt",
        r"osym\s*denem",
    ],
    "Hiz": [
        r"\bh[iı]z\s*(yay|deneme|tyt|ayt|s[iı]nav)",
    ],
    "Avem": [
        r"avem",
    ],
    "Endemik": [
        r"endemik",
    ],
    "Kafa Dengi": [
        r"kafa\s*dengi",
    ],
    "Kultur": [
        r"k[uü]lt[uü]r\s*yay",
    ],
    "Ankara Yay": [
        r"ankara\s*yay",
    ],
    "Bilgi": [
        r"bilgi\s*yay",
    ],
    "Mavi": [
        r"mavi\s*yay",
    ],
    "TG": [
        r"\btg[\-\s]*\d+",          # "TG-3", "TG 5" — sinif test
    ],
    "Bilgi TYT": [
        r"bilgi\s*tyt",
    ],
    "Apotemi TG": [
        r"apotemi\s*tg",
    ],
}


# Tum patternleri tek regex'e birle (performans)
def _build_combined_regex() -> re.Pattern:
    """Tum publisher pattern'larini tek regex'e birletir, named groups ile."""
    parts = []
    for canonical, variants in PUBLISHERS.items():
        # Canonical adi guvenli-name'e cevir (group icin)
        # NOT: Python regex group adi rakamla baslayamaz, prefix "p_" zorunlu
        safe_name = "p_" + re.sub(r"[^a-zA-Z0-9]", "_", canonical)
        for i, var in enumerate(variants):
            parts.append(f"(?P<{safe_name}_{i}>{var})")
    pattern_str = "|".join(parts)
    return re.compile(pattern_str, re.IGNORECASE)


_COMBINED = _build_combined_regex()


def _normalize_text(text: str) -> str:
    """Turkce karakter + lowercase normalize."""
    if not text:
        return ""
    text = text.lower()
    # Aksan/Turkce: kullaniciya dostane yazimlar yakalanmali
    # Patternler zaten varyant icine alinmis — ek normalize gerekmez
    return text


def detect_publisher(text: str) -> Optional[str]:
    """Mesajda yayinevi adi geciyor mu? Geciyorsa kanonik adi don.

    Donus:
        "Sifir Pozitif" / "Apotemi" / vb. veya None.

    Ornek:
        >>> detect_publisher("0 pozitif yayinlari 65 net yaptim")
        'Sifir Pozitif'
        >>> detect_publisher("apotemide 70 net")
        'Apotemi'
        >>> detect_publisher("3d tyt-3 sonuc")
        '3D'
        >>> detect_publisher("merhaba nasilsin")
        None
    """
    if not text:
        return None

    norm = _normalize_text(text)
    m = _COMBINED.search(norm)
    if not m:
        return None

    # Hangi grup match etti?
    for name, value in m.groupdict().items():
        if value is not None:
            # name = "p_Sifir_Pozitif_0" — son _N'i ayir, prefix "p_" cikar
            parts = name.rsplit("_", 1)  # son _N'i ayir
            safe_name = parts[0][2:]  # "p_" prefix cikar
            # safe_name'i geri yayinevi adina cevir
            for canonical in PUBLISHERS:
                if re.sub(r"[^a-zA-Z0-9]", "_", canonical) == safe_name:
                    return canonical
    return None


def extract_net(text: str) -> Optional[float]:
    """Mesajda 'X net' formatinda sayi var mi? Cikar.

    Ornek:
        >>> extract_net("Pozitif 65 net yaptim")
        65.0
        >>> extract_net("apotemide 70 net cikardim")
        70.0
        >>> extract_net("merhaba")
        None
    """
    if not text:
        return None
    # "X net" / "Xnet" / "X.Y net" / "X,Y net"
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*net", text.lower())
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def is_publisher_only_mention(text: str) -> bool:
    """Mesaj kisaca yayinevi adinin etrafinda donuyor mu (net YOK, baska sey YOK)?

    Bu durumda ogrenci muhtemelen 'su denememi getir' ya da 'su denemenin sonucu var mi'
    demeye calisiyor, ama henuz net paylasmamis.

    Ornek:
        >>> is_publisher_only_mention("0 pozitif")
        True
        >>> is_publisher_only_mention("sifir pozitif yayinlari'na baz al")
        True
        >>> is_publisher_only_mention("Pozitif 65 net yaptim")
        False  # net var
    """
    pub = detect_publisher(text)
    if not pub:
        return False
    net = extract_net(text)
    if net is not None:
        return False
    # Kisa mesaj + yayinevi adi var = sadece yayinevi mention
    return len(text) < 80


# Self-test (import sirasinda calisir, ucuz)
if __name__ == "__main__":
    test_cases = [
        ("0 pozitif", "Sifir Pozitif"),
        ("sifir pozitif yayinlari'na baz al", "Sifir Pozitif"),
        ("0 pozitif yayinlari 65 net yaptim", "Sifir Pozitif"),
        ("Pozitif Yayinlari'nda 65 net yaptim", "Sifir Pozitif"),
        ("apotemide 70 net", "Apotemi"),
        ("apotemi tg-3 75 net", "Apotemi"),
        ("3d tyt-3 80 net", "3D"),
        ("3d yayinlari", "3D"),
        ("palme tyt 60 net", "Palme"),
        ("bilgi sarmal 72 oldu", "Bilgi Sarmal"),
        ("yayin denizi 78 net", "Yayin Denizi"),
        ("ucdortbes 55 net", "UcDortBes"),
        ("345 yayinlari", "UcDortBes"),
        ("limit denemesi 50 net", "Limit"),
        ("esen 65 net", "Esen"),
        ("cap denemesinde 80", "Cap"),
        ("karekok yayin", "Karekok"),
        ("tonguc deneme", "Tonguc"),
        ("isler acil 4", "Acil"),
        ("merhaba nasilsin", None),
        ("son denemem nasil", None),
        ("matematik calisma plani", None),
        ("0 ne demek pozitif mi", None),  # math sorusu — false positive olmamali!
    ]
    fail = 0
    for text, expected in test_cases:
        got = detect_publisher(text)
        ok = got == expected
        if not ok:
            print(f"FAIL: '{text}' → got={got!r} expected={expected!r}")
            fail += 1
        else:
            print(f"OK:   '{text}' → {got!r}")
    print(f"\n{len(test_cases)} test, {fail} fail")
