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
    # MODERN FIZIK / KUANTUM / GORELI
    "modern_fizik": {
        "apis": ["arxiv_search", "nasa_image_search"],
        "renderers": ["formula", "sim", "steps"],
        "keywords": [
            "higgs", "kuantum", "kuvant", "foton", "fotoelektrik",
            "compton", "planck", "belirsizlik", "tunel", "tunel",
            "schrodinger", "heisenberg", "einstein",
            "goreceli", "relativite", "spin", "kara delik",
            "evren", "big bang", "atom alti", "atomalti",
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
    """Hint v3 (25.46.3 Neo): MAX tool+render kullan, ama pre-tool TEXT zorunlu.

    Vizyon: kullanici F5 atmasin, butun-bir-deneyim hissetsin.
    Text streaming hizli akar, tool/render beklenirken kullanici text okur.
    Az kullan = eksik cevap. Tum kapasiteyi kullan ama akisi kompozisyonla
    parcalara bol.
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
        "[TOPIC ENRICHMENT HINT] (Brief #24 v3 25.46.3 — Neo direktif)",
        f"Mesajda konu: *{cat}*",
        "",
        "HEDEF: HEM hiz HEM kalite. Tum kapasiteyi kullan, akisi kompozisyonla parcala.",
        "",
        "RENDERER (inline, tool_call YOK -- her zaman uret):",
        f"  Uygun blocklar: {rens}",
        f"  Cevapta MUTLAKA en az 1-2 render block kullan -- kod blogu icinde {first_renderer}.",
        "  Render API beklemez, streaming sirasinda yazilir, ekstra zaman almaz.",
        "  Tek metin yetersizdir -- gorsel/formul/timeline/mermaid ile zenginlestir.",
        "",
        "TOOL/API (her biri 5-15s ekler -- AMA STREAMING ARASINDA KULLAN):",
        f"  Mevcut: {apis}",
        "  Neo direktif: 'her cevabinda bunlari MAX seviyede kullan, bosuna eklemedik'.",
        "  TOOL CAGIR ama PRE-TOOL TEXT ZORUNLU (system_prompt'taki MUTLAK kurali oku).",
        "  Akis: 2-3 cumle text → tool_call → tool sonucu sonrasi devam text + render → kapanis.",
        "  Kullanici beklerken TEXT OKUR -- 60sn bos ekran YASAK, ama az tool YASAK.",
        "  3+ tool cagiracaksan: aralarinda text uret (her tur 1 cumle min).",
        "",
        "KOMPOZISYON KURALI (Neo 'butun-bir-deneyim' vizyonu):",
        "  1. Acilis text (2-3 cumle, streaming akar)",
        "  2. Render block (formula/sim/timeline -- inline)",
        "  3. Tool call (api veri cek)",
        "  4. Tool sonucu sonrasi: ek text + render + ek tool gerekiyorsa",
        "  5. Kapanis: ozet + soru sor (etkilesim devam)",
        "",
        "ASLA: tek mesajda HER SEY (uzun bekleme), kullanici F5 atar.",
        "ASLA: pre-tool text atla (kullanici sessizlik gorur).",
        "ASLA: render kullanma (cevap kuru, eksik kalir).",
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
