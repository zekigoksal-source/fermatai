"""
topic_tool_enricher.py — Brief #24 (Neo 15 May)
================================================

Neo direktifi: Bot her cevap uretirken eldeki render araclari + external API'lerden
faydalanmali. Konu tespiti -> relevant API/renderer hints -> Claude system prompt.

Mevcut sistem (eski):
  enrichment_dispatcher.py  -> user trigger keyword yazinca tepki ver
  renderer_hint_inject.py   -> user mesaj pattern'i -> renderer hint inject

Eksik (bu modul kapatir):
  Konu tabanli PROAKTIF inject -- kullanici Higgs nedir dese, Claude'a
  CERN API + arxiv + mol3d/formula renderer onerisi otomatik onerilsin.

Kullanim:
  from topic_tool_enricher import get_enrichment_hint
  hint = get_enrichment_hint(user_message)
  if hint:
      system_prompt += hint
"""
from __future__ import annotations
import re
from typing import Optional


# Topic -> API + Renderer Mapping
# apis: external API/tool isimleri (Claude tool listesinde olmali)
# renderers: render block tipleri (chart, mol3d, sim, formula, kgraph, steps)
# keywords: tespit icin (text ILIKE match)

TOPIC_ENRICHMENT_MAP = {
    # MODERN FIZIK / KUANTUM / GORELI / PARCACIK FIZIGI
    "modern_fizik": {
        "apis": ["arxiv_search", "nasa_image_search"],
        "renderers": ["formula", "sim", "steps", "mermaid"],
        "keywords": [
            # Bozonlar / temel parcaciklar
            "higgs", "graviton", "boson", "bozon", "kuark", "quark",
            "lepton", "elektron", "muon", "tau ", "notrino", "nötrino",
            "neutrino", "foton", "gluon", "w bozonu", "z bozonu",
            # Kuvvetler + standart model
            "standart model", "kuvant", "kuantum", "spin",
            "fotoelektrik", "compton", "planck",
            "belirsizlik", "tunelleme", "tünelleme", "tunel etk", "tünel etk",
            # Bilim adamlari
            "schrodinger", "schrödinger", "heisenberg", "einstein",
            "dirac", "feynman", "pauli", "bohr",
            # Goreceli / yercekimi kuantizasyon
            "goreceli", "göreceli", "relativite", "relativistik",
            "kuantum yercekim", "kuantum yerçekim", "sicim teori", "string teori",
            "loop kuantum", "supersimetri", "süpersimetri",
            # Kozmoloji
            "kara delik", "evren", "big bang", "buyuk patlama",
            "karanlik madde", "karanlık madde", "karanlik enerji",
            "gravitasyon dalga", "gravitasyonel dalga", "ligo",
            # Detektorler / deneyler
            "lhc", "cern", "atlas", "cms detektor",
            "atom alti", "atomalti", "atom-alti",
        ],
    },
    # KLASIK FIZIK / MEKANIK
    "klasik_fizik": {
        "apis": ["wolfram_query"],
        "renderers": ["formula", "steps", "sim"],
        "keywords": [
            "kuvvet", "hareket", "enerji", "momentum", "newton",
            "kaldirma", "basinc", "tork", "atalet", "yercekim",
            "surtunme", "ivme", "esnek", "esneklik",
        ],
    },
    # ELEKTRIK / MANYETIZMA
    "elektromanyetik": {
        "apis": ["wolfram_query"],
        "renderers": ["formula", "sim", "steps"],
        "keywords": [
            "elektrik", "manyet", "voltaj", "akim", "direnc",
            "ohm", "kondansator", "indukleme", "bobin",
            "kapasitor", "elektromanyetik", "maxwell",
        ],
    },
    # DALGA / OPTIK
    "dalga_optik": {
        "apis": ["wolfram_query"],
        "renderers": ["formula", "sim"],
        "keywords": [
            "dalga", "frekans", "hertz", "ses dalga", "titresim",
            "optik", "kirilma", "yansima", "mercek", "ayna",
            "girisim", "kirinim", "polarizasyon",
        ],
    },
    # KIMYA / MOLEKUL
    "kimya_molekul": {
        "apis": ["pubchem_lookup", "wikipedia_summary"],
        "renderers": ["mol3d", "element", "formula"],
        "keywords": [
            "molekul", "bilesik", "atom yap",
            "kafein", "glukoz", "benzen", "metan", "etanol", "su molekul",
            "amino asit", "protein yap", "dna yap", "kovalent",
            "iyonik", "bag tur", "hibrit",
        ],
    },
    # KIMYA / TEPKIME
    "kimya_tepkime": {
        "apis": ["wolfram_query", "pubchem_lookup"],
        "renderers": ["formula", "steps"],
        "keywords": [
            "tepkime", "reaksiyon", "denklestir",
            "asit baz", "yukseltgenme", "indirgenme",
            "redoks", "elektroliz", "yanma", "notrlesme",
            "kataliz", "molarite",
        ],
    },
    # KIMYA / PERIYODIK CETVEL
    "kimya_element": {
        "apis": ["wikipedia_summary"],
        "renderers": ["element", "formula"],
        "keywords": [
            "periyodik", "yariletken",
            "soygaz", "halojen", "alkali", "toprak alkali",
            "lantanit", "aktinit", "izotop", "elektron diz",
        ],
    },
    # MATEMATIK / KAVRAM
    "matematik_kavram": {
        "apis": ["wolfram_query"],
        "renderers": ["formula", "steps", "desmos", "plotly"],
        "keywords": [
            "turev", "integral", "limit", "polinom", "fonksiyon",
            "logaritma", "ustlu", "trigonometr",
            "matris", "determinant", "vektor",
            "olasilik", "permutasyon",
            "kombinasyon",
        ],
    },
    # GEOMETRI
    "geometri": {
        "apis": ["wolfram_query"],
        "renderers": ["geogebra", "formula", "steps"],
        "keywords": [
            "ucgen", "dortgen", "cember",
            "hacim", "prizma", "piramit",
            "kure", "koordinat", "egim", "analitik geo",
        ],
    },
    # BIYOLOJI / HUCRE
    "biyoloji_hucre": {
        "apis": ["wikipedia_summary", "pubchem_lookup"],
        "renderers": ["mol3d", "kgraph", "sim"],
        "keywords": [
            "hucre", "mitoz", "mayoz", "ribozom", "mitokondri",
            "kloroplast", "endoplazm", "golgi", "lizozom", "cekirdek",
            "stoplazm", "sitoplazm", "membran",
        ],
    },
    # BIYOLOJI / SISTEM
    "biyoloji_sistem": {
        "apis": ["wikipedia_summary"],
        "renderers": ["kgraph", "sim"],
        "keywords": [
            "fotosentez", "solunum", "sindirim", "dolasim",
            "bosaltim", "sinir sistemi", "endokrin",
            "bagisik", "iskelet", "kas sistem", "ureme",
            "uretici",
        ],
    },
    # BIYOLOJI / GENETIK
    "biyoloji_genetik": {
        "apis": ["wikipedia_summary", "pubchem_lookup"],
        "renderers": ["mol3d", "kgraph", "steps"],
        "keywords": [
            "dna", "rna", "kromozom", "kalitim",
            "mutasyon", "evrim", "dogal sec", "mendel",
            "alel", "fenotip", "genotip",
        ],
    },
    # TARIH
    "tarih": {
        "apis": ["wikipedia_summary"],
        "renderers": ["timeline", "map", "kgraph"],
        "keywords": [
            "osmanli", "selcuk", "kurtulus",
            "milli mucad", "ataturk",
            "inkilap", "antlasma",
            "fetih", "padisah", "cumhuriyet",
        ],
    },
    # COGRAFYA
    "cografya": {
        "apis": ["wikipedia_summary", "nasa_image_search"],
        "renderers": ["map", "chart", "sim"],
        "keywords": [
            "cografya", "iklim", "deprem", "volkan", "yagis",
            "ruzgar", "nufus", "harita",
            "kita", "okyanus", "iklim tip", "ekvator", "tropik",
        ],
    },
    # TURKCE / EDEBIYAT
    "edebiyat": {
        "apis": ["wikipedia_summary"],
        "renderers": ["timeline", "kgraph"],
        "keywords": [
            "edebiyat", "yazar", "sair", "roman", "siir",
            "divan edebi", "halk edebi", "tanzimat", "servet",
            "garip", "ikinci yeni", "milli edebi",
            "epik", "lirik", "dramatik",
        ],
    },
}


def detect_topic_category(text: str) -> Optional[str]:
    """Metinde TOPIC_ENRICHMENT_MAP kategorisi tespit et."""
    if not text:
        return None
    tl = text.lower()

    for category, cfg in TOPIC_ENRICHMENT_MAP.items():
        for kw in cfg["keywords"]:
            if kw in tl:
                return category
    return None


def get_enrichment_config(category: str) -> Optional[dict]:
    """Kategori -> config dict."""
    return TOPIC_ENRICHMENT_MAP.get(category)


def get_enrichment_hint(text, channel="wp"):
    """Hint v4 (25.46.5 Neo bug): Text-only cevap TESPIT EDILDI, kural sertlestirildi.

    Neo direktif 18:40: 'Sadece text cok zayif bir mesaj'. v3 hinti soft kaldi.
    v4: MUTLAK ZORUNLU dil + render block YAZMADAN cevap GONDERMEK YASAK.
    """
    cat = detect_topic_category(text)
    if not cat:
        return None
    cfg = TOPIC_ENRICHMENT_MAP[cat]
    rens = ", ".join(cfg["renderers"]) if cfg["renderers"] else "yok"
    apis = ", ".join(cfg["apis"]) if cfg["apis"] else "yok"
    first_renderer = cfg["renderers"][0] if cfg["renderers"] else "formula"

    NL = chr(10)
    parts = [
        "",
        "=================================================================",
        "🚨🚨🚨 [TOPIC ENRICHMENT v4 — MUTLAK ZORUNLU] (Neo bug 15 May 18:40)",
        "=================================================================",
        f"Mesajda konu: *{cat}*",
        "",
        "🚨 NEO BUG (18:40): Sen Higgs sorusuna SADECE TEXT cevap verdin -- ",
        "   Neo 'Sadece text cok zayif bir mesaj' diye uyardi. BU BUG'I TEKRAR ETME!",
        "",
        "🔴🔴🔴 RENDER BLOCK MUTLAK ZORUNLU 🔴🔴🔴",
        f"   Bu kategori icin DOGRU blocklar: {rens}",
        "   CEVAPTA EN AZ 2 RENDER BLOCK KULLANMADAN CEVABI TAMAMLAMA.",
        f"   En basit: kod blogu icinde {first_renderer} ile sembol/formul/sema goster.",
        "   ALTERNATIF blocklar: mermaid (akis), compare2 (vs tablosu), steps (adim adim),",
        "   timeline (tarihce), sim (interaktif), 3d (model), chart (veri).",
        "",
        "   ❌ YASAK: Sadece markdown metin + bullet point (cevap KURU kalir)",
        "   ❌ YASAK: Render kullanmadan 'devam edelim mi?' diye bitirmek",
        "   ❌ YASAK: 'Daha derine gitmek istersen' diye USTUNU ortmek -- DERINE GIR",
        "",
        "   ✅ DOGRU: Kavramsal text → ```formula → mermaid akis → kapanis",
        "   ✅ DOGRU: compare2 ile farkliliklari net vurgu",
        "   ✅ DOGRU: timeline ile tarihsel surec",
        "",
        "🔧 TOOL/API (her biri 5-15s ekler -- DOGRU KULLANIRSAN MUTHIS):",
        f"   Mevcut: {apis}",
        "   PRE-TOOL TEXT MUTLAK (system_prompt'taki kurali oku). Kompozisyon:",
        "   1. Acilis text (2-3 cumle, streaming hizli akar)",
        "   2. Render block #1 (inline, beklemez)",
        "   3. Tool call gerekiyorsa cagir (text okuyor user, sikilmiyor)",
        "   4. Tool sonucu sonrasi: ek text + render #2",
        "   5. Kapanis: ozet + alternatif daldan devam onerisi",
        "",
        "   3+ tool: aralarinda text uret (her tur 1 cumle min).",
        "",
        "📐 NEO 'BUTUN-BIR-DENEYIM' VIZYONU:",
        "   Hedef: kullanici F5 atmasin, text streaming akarken render+tool araya",
        "   girer, kompozisyon olusur. Az render = eksik cevap, az tool = eksik veri.",
        "   Tum kapasite kullanilmali -- ama akis parcalara bolunmus olmali.",
        "",
        "=================================================================",
        "",
    ]
    return NL.join(parts)

def list_categories() -> list[str]:
    return list(TOPIC_ENRICHMENT_MAP.keys())


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test = " ".join(sys.argv[1:])
        cat = detect_topic_category(test)
        print(f"Test: {test!r}")
        print(f"Category: {cat}")
        if cat:
            print(f"Config: {TOPIC_ENRICHMENT_MAP[cat]}")
            print()
            print("Hint preview:")
            print(get_enrichment_hint(test))
    else:
        tests = [
            "Higgs bozonu nedir",
            "kafein molekulunun yapisi",
            "kuvvet ve hareket arasindaki iliski",
            "fotosentez nasil olur",
            "osmanli devleti ne zaman kuruldu",
            "selam nasilsin",
        ]
        for t in tests:
            cat = detect_topic_category(t)
            print(f"{t!r:50} -> {cat}")
