"""
Konu/Ders Tespiti — tüm dosyalar buradan kullanır.

Oturum 20 refactor: bridge + fast_responses + llm_router'daki
farklı keyword listeleri → tek fonksiyon.
"""
import re

# Ders keyword'leri — Türkçe karakter varyantları dahil
_DERS_KEYWORDS = {
    "Fizik": r"fizik|fotoelektrik|kuvvet|enerji|dalga|optik|manyetik|elektrik|newton|ivme",
    "Matematik": r"matematik|mat\b|denklem|fonksiyon|turev|türev|integral|limit|olasilik|olasılık|sayı\s*kume|oran\s*orant",
    "Kimya": r"kimya|periyodik|atom|mol\b|asit|baz|organik|inorganik|tepkime|reaksiyon|element",
    "Biyoloji": r"biyoloji|bio\b|biyol|hucre|hücre|fotosentez|solunum|mitoz|mayoz|genetik|evrim|bitki|canli|bakteri|virus|virüs",
    "Türkçe": r"turkce|türkçe|paragraf|anlam|cumle|cümle|sozcuk|sözcük|edebiyat|yazar|eser|siir|şiir",
    "Tarih": r"tarih|osmanli|osmanlı|milli\s*mucadele|milli\s*mücadele|inkilap|inkılap|ataturk|atatürk|savas|savaş",
    "Coğrafya": r"cografya|coğrafya|iklim|nufus|nüfus|yerlesim|yerleşim|harita|deprem|volkan",
    "Geometri": r"geometri|ucgen|üçgen|dortgen|dörtgen|cember|çember|alan\b|cevre|çevre|kati\s*cisim|katı\s*cisim",
    "Felsefe": r"felsefe|mantik|mantık|bilgi\s*kuram|etik|estetik|metafizik|epistemoloji",
}

# Konu → Ders eşleştirme (daha spesifik konular)
_KONU_DERS_MAP = {
    "Fizik": [
        "kaldirma kuvveti", "kaldırma kuvveti", "basinc", "basınç", "hareket",
        "hiz", "hız", "moment", "tork", "sicaklik", "sıcaklık", "elektrik",
        "manyetizma", "dalga", "optik", "fotoelektrik", "atom modeli",
    ],
    "Matematik": [
        "denklem", "esitsizlik", "eşitsizlik", "fonksiyon", "logaritma",
        "polinom", "turev", "türev", "integral", "limit", "olasilik",
        "permutasyon", "kombinasyon", "sayi kumeleri", "sayı kümeleri",
    ],
    "Biyoloji": [
        "hucre", "hücre", "mitoz", "mayoz", "fotosentez", "solunum",
        "sindirim", "bosaltim", "boşaltım", "dolasim", "dolaşım",
        "sinir sistemi", "bagisiklik", "bağışıklık", "genetik", "evrim",
        "bitki", "hayvan", "bakteri", "virus", "virüs", "ekoloji",
    ],
    "Kimya": [
        "periyodik", "atom", "mol", "asit", "baz", "tepkime", "reaksiyon",
        "organik", "inorganik", "element", "bilesik", "bileşik", "madde",
    ],
}


def detect_subject(text: str) -> str | None:
    """
    Metinden ders/konu tespit et. Ders adı döner veya None.
    Örnek: "kaldırma kuvveti nedir" → "Fizik"
    """
    text_lower = text.lower()

    # 1. Spesifik konu eşleştirme (daha isabetli)
    for ders, konular in _KONU_DERS_MAP.items():
        for konu in konular:
            if konu in text_lower:
                return ders

    # 2. Genel keyword eşleştirme
    for ders, pattern in _DERS_KEYWORDS.items():
        if re.search(pattern, text_lower):
            return ders

    return None


def detect_exam_type(text: str) -> str | None:
    """TYT/AYT/LGS tespiti."""
    text_lower = text.lower()
    if re.search(r'\bayt\b', text_lower):
        return "AYT"
    if re.search(r'\btyt\b', text_lower):
        return "TYT"
    if re.search(r'\blgs\b', text_lower):
        return "LGS"
    if re.search(r'\byks\b', text_lower):
        return "YKS"
    return None
