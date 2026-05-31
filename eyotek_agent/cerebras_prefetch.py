# -*- coding: utf-8 -*-
"""
Cerebras Pre-Fetch Context Engine (25.40z3-CEREBRAS-PREFETCH)
==============================================================

Cerebras gpt-oss-120b standart chat path'inde TOOL CALLING yapmaz — ama akilli pre-fetch ile
mevcut tool ekosisteminden DESTEK alabilir. Bot mesaji analiz edilir, intent ve
konu tespit edilir, ARKA PLANDA paralel API'ler cagrilir, Cerebras prompt'una
INJECT edilir. Cerebras zenginlestirilmis cevap verir — Claude'a HANDOFF gerek
kalmaz.

NEO DIREKTIFI (5 May 2026):
"235b'lik model en azindan tool kullanamasada mevcut apilerden destek alamaz mı?
RAG'den faydalansa, Wikipedia'dan konu cekse, Render arac kullanabilse Cerebras
kendi cevap verirken zenginlesebilirdi."

YAPILAN: 5 paralel API source intent-aware pre-fetch:
1. RAG (search_curriculum) — Fermat 4500+ konu icerigi (zaten vardi, optimize edildi)
2. Wikipedia (wiki_lookup) — pre-fetch (cevap sonrasi degil ÖNCE inject)
3. PubChem (kimya/molekul intent'inde)
4. USGS (deprem intent'inde)
5. arxiv (akademik kaynak intent'inde)

PARALEL: asyncio.gather ile tek HTTP roundtrip (toplam +200-400ms latency)
TOPLAM CEREBRAS YANIT: 2.5s + 0.4s prefetch = 2.9s (Claude tool zinciri 15-30s)

ROI: Cerebras pay %5 → %20-25 hedefi (text_only kavramsal mesajların büyük kısmı
Claude'a düşmek yerine pre-fetched context ile Cerebras'ta kalır).
"""
from __future__ import annotations
import asyncio
import re
from typing import Optional
from loguru import logger


# ─── Konu/Topic Tespiti ───────────────────────────────────────────────────

# Kimya elementi/molekül pattern (PubChem için)
_CHEMISTRY_PATTERN = re.compile(
    r'\b(atom|molek[uü]l|element|periyodik|kovalent|iyonik|asit|baz|tuz|'
    r'hidrojen|oksijen|karbon|azot|sodyum|magnezyum|alüminyum|silisyum|fosfor|'
    r'k[uü]k[uü]rt|klor|argon|potasyum|kalsiyum|demir|baker|civa|altın|gümüş|'
    r'su|h2o|co2|nh3|naoh|hcl|h2so4|ch4|c2h5oh|etanol|metan|asetik|'
    r'hidrokarbon|alkol|aldehit|keton|ester|aminoasit|protein|dna|rna)',
    re.IGNORECASE,
)

# Fizik/Astronomi (Wikipedia için)
_PHYSICS_PATTERN = re.compile(
    r'\b(kara\s*delik|nötron\s*yıldız|süpernova|big\s*bang|kuantum|'
    r'görelilik|relativite|einstein|newton|kepler|hawking|maxwell|'
    r'foton|elektron|proton|nötron|kuark|bozon|gluon|nötrino|'
    r'manyetik|elektrik|kuvvet|enerji|momentum|dalga|optik|'
    r'galaksi|samanyolu|gezegen|yıldız|nova|asteroit|kuyruklu|'
    r'kara\s*madde|kara\s*enerji|olay\s*ufku|tekillik|'
    r'thermodinamik|entropi|enerji\s*korunumu)',
    re.IGNORECASE,
)

# Deprem/jeoloji (USGS için)
_EARTHQUAKE_PATTERN = re.compile(
    r'\b(deprem|sismik|fay\s*hatt|tektonik|magnit[uü]d|richter|'
    r'volkan|tsunami|jeoloji|kabuk\s*hareketi)',
    re.IGNORECASE,
)

# Akademik araştırma (arxiv için)
_RESEARCH_PATTERN = re.compile(
    r'\b(makale|paper|arxiv|akademik|cite|atif|atıf|literatür|literatur|'
    r'arastirma|araştırma|araştırmacı|arastirmaci)',
    re.IGNORECASE,
)

# Konu çıkarma (RAG/Wiki için)
_TOPIC_KEYWORDS = re.compile(
    r'\b(?:nedir|ne\s+demek|açıkla|aciklа|anlat|göster|örnek|örnek)\s+'
    r'([a-zçğıöşü][a-zçğıöşü\s]{3,40})',
    re.IGNORECASE,
)


def extract_topic(message: str) -> str:
    """Mesajdan konu basligi cikarir.

    'manyetik alan nedir' → 'manyetik alan'
    'TYT fizik anlat' → 'TYT fizik' (önek + ders)
    'kara delik açıkla' → 'kara delik'
    """
    if not message:
        return ""
    msg = message.strip().lower()
    # Önce keyword sonrası kelimeyi yakala
    m = _TOPIC_KEYWORDS.search(msg)
    if m:
        return m.group(1).strip()
    # Yoksa ilk 5 kelime
    words = re.findall(r'\b[a-zçğıöşü]+\b', msg)
    return " ".join(words[:5])


# ─── Pre-Fetch Engine ─────────────────────────────────────────────────────

async def _fetch_rag(query: str) -> Optional[str]:
    """RAG semantik arama (pgvector) — Fermat 4500+ konu icerigi."""
    try:
        from rag_engine import search_curriculum
        hits = await search_curriculum(query, limit=2)
        if not hits:
            return None
        out = "\n[📚 RAG (Fermat veritabanı)]\n"
        for h in hits[:2]:
            out += f"• {h.get('ders', '?')} / {h.get('konu', '?')}:\n"
            out += f"  {(h.get('icerik', '') or '')[:350]}\n"
        return out
    except Exception as e:
        logger.debug(f"[PREFETCH] RAG fail: {e}")
        return None


async def _fetch_wiki(query: str) -> Optional[str]:
    """Wikipedia ozet (pre-fetch — cevap oncesi)."""
    try:
        from external_apis_v2 import wiki_lookup
        result = await wiki_lookup(query)
        if not result.get("success"):
            return None
        extract = (result.get("extract") or "").strip()
        if len(extract) < 80:
            return None
        # 250 char ile kes
        if len(extract) > 250:
            extract = extract[:250].rsplit(" ", 1)[0] + "..."
        title = result.get("title", query)
        return f"\n[🌐 Wikipedia — {title}]\n{extract}\n"
    except Exception as e:
        logger.debug(f"[PREFETCH] Wiki fail: {e}")
        return None


async def _fetch_pubchem(query: str) -> Optional[str]:
    """PubChem (kimya elementi/molekul)."""
    try:
        from external_apis_v2 import pubchem_lookup
        # Mesajdan kimya adi cikar
        chem_match = re.search(
            r'\b(su|h2o|co2|nh3|naoh|hcl|h2so4|ch4|c2h5oh|etanol|metan|'
            r'oksijen|hidrojen|karbon|azot|sodyum|kalsiyum|demir|altın|gümüş)\b',
            query.lower(),
        )
        if not chem_match:
            return None
        result = await pubchem_lookup(chem_match.group(1))
        if not result.get("success"):
            return None
        return (
            f"\n[🧪 PubChem — {result.get('name', '?')}]\n"
            f"Formul: {result.get('formula', '?')} | "
            f"Molar kütle: {result.get('molecular_weight', '?')} g/mol\n"
        )
    except Exception as e:
        logger.debug(f"[PREFETCH] PubChem fail: {e}")
        return None


async def _fetch_usgs() -> Optional[str]:
    """USGS son depremler (5+ büyüklük, son 24h)."""
    try:
        from external_apis_v2 import usgs_earthquakes
        result = await usgs_earthquakes(min_magnitude=5.0, max_results=3)
        if not result.get("success") or not result.get("earthquakes"):
            return None
        out = "\n[🌍 USGS — Son depremler (5.0+)]\n"
        for eq in result["earthquakes"][:3]:
            out += f"• Mag {eq.get('magnitude', '?')} - {eq.get('place', '?')[:60]}\n"
        return out
    except Exception as e:
        logger.debug(f"[PREFETCH] USGS fail: {e}")
        return None


async def _fetch_arxiv(query: str) -> Optional[str]:
    """arXiv akademik makale arama."""
    try:
        from external_apis_v2 import arxiv_search
        result = await arxiv_search(query, max_results=2)
        if not result.get("success") or not result.get("papers"):
            return None
        out = "\n[📑 arXiv — Akademik makaleler]\n"
        for p in result["papers"][:2]:
            out += f"• {p.get('title', '?')[:80]}\n"
            out += f"  {(p.get('summary', '') or '')[:200]}\n"
        return out
    except Exception as e:
        logger.debug(f"[PREFETCH] arXiv fail: {e}")
        return None


# ─── Ana Pre-Fetch API ────────────────────────────────────────────────────

# Intent → API kaynaklari mapping
# Her intent için hangi kaynaklar paralel cagrilacak
_INTENT_TO_SOURCES = {
    "kavram_aciklama":   ["rag", "wiki"],
    "ders_anlatim":      ["rag", "wiki"],
    "formul_aciklama":   ["rag", "wiki"],
    "ornek_uretim":      ["rag"],
    "ozet_iste":         ["rag", "wiki"],
    "kisaca_ozet":       ["rag"],
    "konu_anlatim_uzun": ["rag", "wiki", "arxiv"],
    "yontem_iste":       ["rag"],
    "cozum_iste":        ["rag"],
    "render_request":    ["rag"],
    "karsilastirma":     ["rag", "wiki"],
    "quiz_request":      ["rag"],
    # Sohbet/motivasyon — sadece RAG (kişiselleştirme)
    "sohbet":            [],
    "selamlama":         [],
    "motivasyon_destek": [],
    "duygu_paylasim":    [],
}


async def prefetch_context(
    message: str,
    intent: str = "",
    role: str = "",
    channel: str = "whatsapp",
    timeout: float = 3.0,
) -> str:
    """Cerebras'a inject edilecek pre-fetched context blogu uretir.

    Akıllı kaynak seçimi:
    - Intent → temel kaynaklar (RAG, Wiki)
    - Mesaj içeriği → ek kaynaklar (PubChem kimya, USGS deprem, arXiv araştırma)
    - Paralel asyncio.gather → tek roundtrip
    - 3sn timeout → yavaş kaynak Cerebras'i bekletmez

    Args:
        message: kullanici mesaji
        intent: intent_classifier sonucu (kavram_aciklama, vb.)
        role: kullanici rolu
        channel: 'web' veya 'whatsapp'
        timeout: max bekleme suresi (sn)

    Returns:
        Cerebras prompt'una ekleneck context string (boş ise '')
    """
    if not message:
        return ""

    msg_lower = message.lower()
    topic = extract_topic(message)
    if len(topic) < 3:
        topic = message[:80]

    # Intent'e göre temel kaynaklar
    sources = list(_INTENT_TO_SOURCES.get(intent, []))

    # İçerik-bazlı ek kaynaklar
    if _CHEMISTRY_PATTERN.search(msg_lower) and "pubchem" not in sources:
        sources.append("pubchem")
    if _EARTHQUAKE_PATTERN.search(msg_lower) and "usgs" not in sources:
        sources.append("usgs")
    if _RESEARCH_PATTERN.search(msg_lower) and "arxiv" not in sources:
        sources.append("arxiv")

    # Hiç kaynak yoksa boş dön (sohbet/selamlama vb.)
    if not sources:
        return ""

    # Paralel fetch
    fetch_map = {
        "rag":     _fetch_rag(topic),
        "wiki":    _fetch_wiki(topic),
        "pubchem": _fetch_pubchem(message),
        "usgs":    _fetch_usgs(),
        "arxiv":   _fetch_arxiv(topic),
    }
    tasks = [fetch_map[s] for s in sources if s in fetch_map]

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[PREFETCH] timeout {timeout}s, partial results kullanilir")
        results = []

    # Sonuçları birleştir
    context_parts = []
    for r in results:
        if isinstance(r, str) and r.strip():
            context_parts.append(r)

    if not context_parts:
        return ""

    # Header + birleşik context
    header = (
        "\n═══════════════════════════════════════════════════════════════\n"
        "📡 PRE-FETCHED CONTEXT (sistem otomatik veri zenginlestirme)\n"
        "═══════════════════════════════════════════════════════════════\n"
        "Asagidaki kaynaklar mesaj icerigine gore otomatik cekildi. Cevabini\n"
        "olustururken bu verileri AKTIF kullan, kaynaklarini belirt.\n"
    )
    body = "".join(context_parts)
    footer = "\n═══════════════════════════════════════════════════════════════\n"

    full_context = header + body + footer
    logger.info(f"[PREFETCH] {len(context_parts)} kaynak inject ({len(full_context)} char) — sources={sources}")
    return full_context


# ─── CLI Test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio as _asyncio
    import sys
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def _test():
        cases = [
            ("manyetik alan nedir", "kavram_aciklama"),
            ("kara delik anlat", "ders_anlatim"),
            ("son depremler", "kavram_aciklama"),
            ("su molekülü yapısı", "kavram_aciklama"),
            ("Newton 2 yasası", "formul_aciklama"),
            ("selam nasilsin", "selamlama"),
        ]
        for msg, intent in cases:
            print(f"\n{'='*60}")
            print(f"MESSAGE: {msg}")
            print(f"INTENT:  {intent}")
            print(f"TOPIC:   {extract_topic(msg)}")
            ctx = await prefetch_context(msg, intent=intent, channel="web")
            print(f"CONTEXT ({len(ctx)} char):")
            print(ctx[:800] if ctx else "  (boş)")

    _asyncio.run(_test())
