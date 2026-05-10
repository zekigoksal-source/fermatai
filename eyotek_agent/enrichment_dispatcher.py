"""
Enrichment Dispatcher — 25.40y (Neo "max kalite cevap" direktifi)
==================================================================

Cerebras cevap verdikten sonra footer ile "💡 [3d] [video] [deney]" göster.
Kullanici trigger keyword yazarsa (3d / video / deney / cozum / grafik):
  → Bu dispatcher tetiklenir
  → Claude'a GITMEDEN (30K token tasarruf!) ilgili bedava API/render çağrılır
  → Sonuç direkt kullanıcıya gönderilir

MIMARI:
  Cerebras footer "💡 deney yaz" → Kullanici "deney" yazar
       ↓
  fast_responses pattern → enrichment_dispatcher
       ↓
  detect_enrichment_intent(message) → ("phet", "kaldirma kuvveti")
       ↓
  dispatch_enrichment(intent, konu) → render block VEYA tool result
       ↓
  Direkt kullaniciya (Claude tetiklenmez)

KAZANIM:
- Bedava API'ler Claude prompt 30K token okutmadan çalisir
- Kullanici Cerebras'in onerdigi enrichment'a anlik ulasir
- Maliyet: $0 (bedava API'ler), Cerebras zaten cevap verdi
"""
from __future__ import annotations
import re
from typing import Optional
from loguru import logger


# ─── Trigger Keyword Detection ──────────────────────────────────────────────

ENRICH_TRIGGERS = {
    # 3D / Animasyon
    "3d":          {"intent": "3d", "render": True},
    "üc d":        {"intent": "3d", "render": True},
    "uc d":        {"intent": "3d", "render": True},
    "animasyon":   {"intent": "3d", "render": True},
    "animation":   {"intent": "3d", "render": True},
    "gorsel":      {"intent": "3d", "render": True},

    # PhET deney
    "deney":       {"intent": "phet", "api": True},
    "phet":        {"intent": "phet", "api": True},
    "simulasyon":  {"intent": "phet", "api": True},
    "simülasyon":  {"intent": "phet", "api": True},

    # Wolfram çözüm
    "cozum":       {"intent": "wolfram", "api": True},
    "çözüm":       {"intent": "wolfram", "api": True},
    "adim adim":   {"intent": "wolfram", "api": True},
    "wolfram":     {"intent": "wolfram", "api": True},

    # Desmos grafik
    "grafik":      {"intent": "desmos", "render": True},
    "desmos":      {"intent": "desmos", "render": True},
    "cizim":       {"intent": "desmos", "render": True},
    "çizim":       {"intent": "desmos", "render": True},

    # Video
    "video":       {"intent": "youtube", "tool": "find_youtube_lesson"},
    "youtube":     {"intent": "youtube", "tool": "find_youtube_lesson"},
    "anlatim":     {"intent": "youtube", "tool": "find_youtube_lesson"},
    "anlatım":     {"intent": "youtube", "tool": "find_youtube_lesson"},

    # Çıkmış soru
    "ornek soru":  {"intent": "exam", "tool": "list_exam_questions"},
    "ornek":       {"intent": "exam", "tool": "list_exam_questions"},
    "örnek":       {"intent": "exam", "tool": "list_exam_questions"},
    "cikmis":      {"intent": "exam", "tool": "list_exam_questions"},
    "çıkmış":      {"intent": "exam", "tool": "list_exam_questions"},

    # NASA
    "nasa":        {"intent": "nasa", "tool": "nasa_image_search"},
    "uzay":        {"intent": "nasa", "tool": "nasa_image_search"},

    # PubChem (kimya)
    "molekul":     {"intent": "pubchem", "tool": "pubchem_lookup"},
    "molekül":     {"intent": "pubchem", "tool": "pubchem_lookup"},
    "detay":       {"intent": "pubchem_or_wiki", "tool": "auto"},

    # Harita / coğrafya
    "harita":      {"intent": "map", "render": True},

    # ArXiv / Wikipedia
    "makale":      {"intent": "arxiv", "tool": "arxiv_search"},
    "wiki":        {"intent": "wikipedia", "tool": "wikipedia_summary"},
}


def detect_enrichment_intent(message: str) -> Optional[dict]:
    """Kullanici mesajinda enrichment trigger var mi?

    Returns: {"intent": "phet", "type": "api"} veya None
    """
    if not message:
        return None
    msg = message.lower().strip()
    # Kisa mesaj olmali (1-3 kelime). Uzun mesajlarda trigger gormezden gel.
    if len(msg.split()) > 4:
        return None

    for keyword, info in ENRICH_TRIGGERS.items():
        # Word boundary ile ara
        if re.search(rf"\b{re.escape(keyword)}\b", msg):
            return {
                "intent": info["intent"],
                "trigger_keyword": keyword,
                "type": "render" if info.get("render") else
                        "api"    if info.get("api")    else
                        "tool",
                "tool_name": info.get("tool"),
            }
    return None


# ─── Konu Çıkarımı (Cerebras'in son cevabindan) ─────────────────────────────

async def get_last_topic(phone: str) -> Optional[dict]:
    """Son bot cevabindan konu cikar — son 5 dk."""
    from db_pool import db_fetchrow
    try:
        row = await db_fetchrow(
            """SELECT content FROM agent_conversations
               WHERE phone=$1 AND message_role='assistant'
                 AND created_at > NOW() - INTERVAL '5 minutes'
                 AND content NOT LIKE '[tool_calls%'
               ORDER BY created_at DESC LIMIT 1""",
            phone,
        )
        if not row:
            return None
        content = row["content"] or ""
        # Konu keyword tespiti — Cerebras cevabinda gecen ders/konu
        TOPIC_HINTS = {
            "kaldirma": ("fizik", "kaldırma kuvveti"),
            "kaldırma": ("fizik", "kaldırma kuvveti"),
            "fotoelektrik": ("fizik", "fotoelektrik olay"),
            "newton": ("fizik", "Newton yasaları"),
            "elektrik": ("fizik", "elektrik"),
            "manyetik": ("fizik", "manyetizma"),
            "atom":     ("kimya", "atom"),
            "molekul":  ("kimya", "molekül"),
            "molekül":  ("kimya", "molekül"),
            "tepkime":  ("kimya", "kimyasal tepkimeler"),
            "asit":     ("kimya", "asit baz"),
            "hücre":    ("biyoloji", "hücre"),
            "hucre":    ("biyoloji", "hücre"),
            "dna":      ("biyoloji", "DNA"),
            "protein":  ("biyoloji", "protein"),
            "fotosentez": ("biyoloji", "fotosentez"),
            "türev":    ("matematik", "türev"),
            "turev":    ("matematik", "türev"),
            "integral": ("matematik", "integral"),
            "limit":    ("matematik", "limit"),
            "fonksiyon": ("matematik", "fonksiyonlar"),
            "denklem":  ("matematik", "denklemler"),
            "geometri": ("geometri", "geometri"),
            "üçgen":    ("geometri", "üçgen"),
            "ucgen":    ("geometri", "üçgen"),
            "çember":   ("geometri", "çember"),
            "cember":   ("geometri", "çember"),
            "kara delik": ("astronomi", "kara delik"),
            "yıldız":   ("astronomi", "yıldız"),
            "galaksi":  ("astronomi", "galaksi"),
        }
        cl = content.lower()
        for kw, (ders, konu) in TOPIC_HINTS.items():
            if kw in cl:
                return {"ders": ders, "konu": konu}
        return None
    except Exception:
        return None


# ─── Dispatch — Tool/API Çağırma ────────────────────────────────────────────

async def dispatch_enrichment(intent_info: dict, phone: str) -> Optional[str]:
    """Trigger detect edildi, ilgili enrichment'i tetikle.

    Returns: WhatsApp/Web gönderilecek hazir mesaj (markdown), veya None.
    """
    intent = intent_info["intent"]
    topic = await get_last_topic(phone)

    if not topic:
        # Son konu bulunamadi — generic yardim mesaji
        return (
            "💡 Enrichment için konuyu hatırlayamadım — son sorduğun "
            "konuyu tekrar yazar mısın?"
        )

    ders = topic["ders"]
    konu = topic["konu"]

    try:
        if intent == "phet":
            return _phet_enrichment(ders, konu)
        elif intent == "wolfram":
            return await _wolfram_enrichment(konu)
        elif intent == "youtube":
            return await _youtube_enrichment(konu, phone=phone)
        elif intent == "exam":
            return await _exam_enrichment(ders, konu)
        elif intent == "nasa":
            return await _nasa_enrichment(konu)
        elif intent == "pubchem" or (intent == "pubchem_or_wiki" and ders == "kimya"):
            return await _pubchem_enrichment(konu)
        elif intent == "wikipedia" or intent == "pubchem_or_wiki":
            return await _wikipedia_enrichment(konu)
        elif intent == "arxiv":
            return await _arxiv_enrichment(konu)
        elif intent == "3d":
            return _3d_enrichment(ders, konu)
        elif intent == "desmos":
            return _desmos_enrichment(konu)
        elif intent == "map":
            return _map_enrichment(konu)
    except Exception as e:
        logger.warning(f"  [ENRICH_DISPATCH] {intent} fail: {e}")
        return None

    return None


# ─── Tek-tek Enrichment Fonksiyonları ───────────────────────────────────────

def _phet_enrichment(ders: str, konu: str) -> str:
    """PhET interaktif simulasyon linki."""
    PHET_MAP = {
        "kaldırma kuvveti": "buoyancy",
        "newton yasaları":  "forces-and-motion-basics",
        "elektrik":         "circuit-construction-kit-dc",
        "manyetizma":       "magnet-and-compass",
        "atom":             "build-an-atom",
        "fotoelektrik olay": "photoelectric",
    }
    sim = PHET_MAP.get(konu.lower())
    if sim:
        url = f"https://phet.colorado.edu/sims/html/{sim}/latest/{sim}_tr.html"
        return (
            f"🎮 *PhET — {konu}*\n\n"
            f"Interaktif simülasyon hazır! Aşağıdaki linke tıkla:\n\n"
            f"🔗 {url}\n\n"
            f"_Parametreleri değiştirerek deneyim yapabilirsin._"
        )
    return (
        f"🎮 PhET kütüphanesinde *{konu}* için doğrudan simülasyon yok, "
        f"ama benzer konuları https://phet.colorado.edu/tr/simulations/filter "
        f"adresinden bulabilirsin."
    )


async def _wolfram_enrichment(konu: str) -> str:
    """Wolfram step-by-step çözüm."""
    try:
        from external_apis_v2 import wolfram_step_by_step
        result = await wolfram_step_by_step(konu)
        if result.get("success"):
            steps_text = result.get("answer") or result.get("plaintext", "")
            return f"🔢 *Wolfram — {konu} adım adım*\n\n{steps_text[:1500]}"
    except Exception:
        pass
    return f"🔢 Wolfram çözümü için bir alt başlık dene (örn. *{konu} örneği*)."


async def _youtube_enrichment(konu: str, phone: str = "") -> str:
    """YouTube whitelist kanalları (Tonguç, Hocalara Geldik, vs.).
    25.40z-Neo: phone ile history exclude — ayni video tekrar gelmesin."""
    try:
        from youtube_client import search_videos
        result = await search_videos(konu=konu, limit=2, exclude_phone=phone)
        if result.get("success") and result.get("videos"):
            vids = result["videos"][:2]
            lines = [f"📺 *Konu Anlatımı — {konu}*\n"]
            for v in vids:
                lines.append(f"• [{v.get('channel', 'Eğitim')}] {v.get('title', '')[:80]}")
                lines.append(f"  🔗 {v.get('url', '')}")
            if result.get("total_candidates", 0) > 2:
                lines.append(f"\n_({result['total_candidates']} aday içinden ilk 2 — tekrar 'video' yazarsan farklı önereceğim)_")
            return "\n".join(lines)
    except Exception:
        pass
    return f"📺 *{konu}* için YouTube'da arama yapılamadı, tekrar dene."


async def _exam_enrichment(ders: str, konu: str) -> str:
    """Çıkmış soru kataloğu."""
    try:
        from rag_engine import search_curriculum
        results = await search_curriculum(query=konu, ders=ders, limit=3)
        if results:
            lines = [f"📝 *Çıkmış Sorular — {konu}*\n"]
            for r in results[:3]:
                lines.append(f"• {r.get('konu', konu)} — {r.get('icerik', '')[:120]}")
            lines.append("\n_Tam soruyu görmek için 'soru goster' yaz._")
            return "\n".join(lines)
    except Exception:
        pass
    return f"📝 *{konu}* için RAG'da çıkmış soru taraması yapılıyor — biraz bekle."


async def _nasa_enrichment(konu: str) -> str:
    """NASA görseli."""
    try:
        from external_apis_v2 import nasa_image_search
        result = await nasa_image_search(konu)
        if result.get("success") and result.get("items"):
            item = result["items"][0]
            return (
                f"🌌 *NASA — {konu}*\n\n"
                f"*{item.get('title', '')}*\n\n"
                f"🔗 {item.get('href', '')}\n\n"
                f"_{item.get('description', '')[:300]}_"
            )
    except Exception:
        pass
    return f"🌌 NASA arşivinde *{konu}* için görsel aranıyor."


async def _pubchem_enrichment(konu: str) -> str:
    """PubChem molekül detay."""
    try:
        from external_apis_v2 import pubchem_lookup
        result = await pubchem_lookup(konu)
        if result.get("success"):
            return (
                f"⚗️ *PubChem — {konu}*\n\n"
                f"*Formül:* {result.get('formula', '?')}\n"
                f"*Molekül ağırlığı:* {result.get('molecular_weight', '?')}\n"
                f"*CID:* {result.get('cid', '?')}\n\n"
                f"_3D modeli için 'mol3d {konu}' yaz._"
            )
    except Exception:
        pass
    return f"⚗️ PubChem'de *{konu}* aranıyor."


async def _wikipedia_enrichment(konu: str) -> str:
    """Wikipedia özet."""
    try:
        from external_apis_v2 import wikipedia_summary
        result = await wikipedia_summary(konu, lang="tr")
        if result.get("success"):
            return (
                f"📚 *Wikipedia — {konu}*\n\n"
                f"{result.get('extract', '')[:600]}\n\n"
                f"🔗 {result.get('url', '')}"
            )
    except Exception:
        pass
    return f"📚 Wikipedia'da *{konu}* aranıyor."


async def _arxiv_enrichment(konu: str) -> str:
    """ArXiv bilimsel makale."""
    try:
        from external_apis_v2 import arxiv_search
        result = await arxiv_search(konu, max_results=2)
        if result.get("success") and result.get("papers"):
            lines = [f"🌟 *ArXiv — {konu}* (bilimsel makaleler)\n"]
            for p in result["papers"]:
                lines.append(f"• *{p.get('title', '')[:80]}*")
                lines.append(f"  {p.get('authors', '')[:60]}")
                lines.append(f"  🔗 {p.get('url', '')}")
            return "\n".join(lines)
    except Exception:
        pass
    return f"🌟 ArXiv'te *{konu}* aranıyor."


def _3d_enrichment(ders: str, konu: str) -> str:
    """3D Three.js render link önerisi."""
    THREE_PRESETS = {
        "atom":           "atom_proper",
        "molekül":        "mol3d",
        "DNA":            "dna_helix",
        "hücre":          "hucre",
        "kara delik":     "blackhole",
        "galaksi":        "galaxy",
        "manyetizma":     "magnetic_field",
        "elektrik":       "circuit",
    }
    preset = THREE_PRESETS.get(konu.lower())
    if preset:
        return (
            f"🌀 *3D Animasyon — {konu}*\n\n"
            f"```3d\n"
            f'{{"scene":"{preset}","title":"{konu}"}}\n'
            f"```\n\n"
            f"_Web kanalında interaktif 3D model olarak görünür (sürükle/zoom)._"
        )
    return (
        f"🌀 *{konu}* için hazır 3D preset yok. Genel 3D blok için "
        f"konunun temel parametrelerini söyle (örn. 'atom modeli' / 'hücre yapısı')."
    )


def _desmos_enrichment(konu: str) -> str:
    """Desmos grafik embed önerisi."""
    return (
        f"📐 *Desmos — {konu}*\n\n"
        f"🔗 https://www.desmos.com/calculator?lang=tr\n\n"
        f"_Konunun fonksiyonunu yaz, sana özel grafik için tekrar 'grafik [fonksiyon]' yazabilirsin._\n"
        f"_Örnek:_ `grafik y=x^2`"
    )


def _map_enrichment(konu: str) -> str:
    return (
        f"🗺 *Harita — {konu}*\n\n"
        f"🔗 https://www.google.com/maps/search/{konu.replace(' ', '+')}\n\n"
        f"_Daha detaylı harita/uydu görüntü için 'detay [bölge]' yaz._"
    )


# ─── 25.40z — Wikipedia Direct Enrichment ───────────────────────────────────

# Cerebras kavramsal cevabı verdiğinde arka planda Wikipedia extract
# enjekte et. Kullanıcı ek tıklama yapmadan kaynak görür.

# Hangi konularda otomatik ekle (akademik kavram tespiti)
_WIKI_ENRICH_TOPICS = [
    # Bilim — fizik
    "atom", "elektron", "proton", "neutron", "kuantum", "newton", "einstein",
    "yerçekim", "yercekim", "kara delik", "fotoelektrik", "elektromanyetik",
    "termodinami", "entropi", "rölativ", "relativ",
    # Bilim — kimya
    "periyodik", "molekül", "element", "asit", "baz", "tepkime", "katalizör",
    "organik", "inorganik", "polimer",
    # Bilim — biyoloji
    "hücre", "dna", "rna", "protein", "enzim", "fotosentez", "mitoz", "mayoz",
    "evrim", "darwin", "ekosistem",
    # Matematik
    "türev", "integral", "limit", "fourier", "vektör", "matris",
    "logaritma", "trigonom", "geometri", "öklid",
    # Tarih (bilimsel/edebi figür)
    "atatürk", "osmanlı", "kurtuluş", "cumhuriyet", "tarih",
    # Edebiyat
    "reşat nuri", "yaşar kemal", "orhan pamuk", "nazım hikmet",
    "tanzimat", "servet-i fünun", "milli edebiyat",
    # Astronomi
    "galaksi", "yıldız", "gezegen", "güneş sistemi", "samanyolu", "andromeda",
    "kepler", "hubble",
]


def _detect_wiki_topic(user_msg: str, bot_response: str) -> str | None:
    """User mesajı + bot cevabından Wikipedia için sorgu çıkar.

    Strateji:
    1. User mesajında akademik kavram var mı?
    2. Bot cevabında geçen büyük harfle başlayan terim (özel ad)?
    3. Hiçbiri yoksa None — ekleme yapma.
    """
    if not user_msg or not bot_response:
        return None
    msg_l = user_msg.lower().strip()

    # 1. User mesajında ne soruldu — keyword tespit
    for kw in _WIKI_ENRICH_TOPICS:
        if kw in msg_l:
            # User mesajından konu cümlesini çıkar (ilk 6 kelime)
            words = user_msg.split()[:6]
            return " ".join(words).rstrip("?.!,").strip()

    # 25.43-WIKI-FIX (Neo bug 11 May): Step 2 (Title Case fallback) KALDIRILDI.
    # Sebep: Bot cevabında geçen RANDOM Title Case kelime'yi Wikipedia'ya yolluyordu →
    # alakasız sonuçlar:
    #   "Ankara hava" cevabında "Şu'ara Suresi" (Kuran suresi) çıktı
    #   "Behavior rule" cevabında "Claude Monet" (ressam) çıktı
    #   "Örsel" cevabında "Victor Orsel" (Fransız ressam) çıktı
    #   "Erciyes" cevabında "Zeki Bey" (Osmanlı bürokratı) çıktı
    # Title Case fallback %90 alakasız content getiriyordu — kaldırıldı.
    # Sadece whitelist akademik keyword match (step 1) ile Wikipedia eklenir.
    return None


async def inject_wiki_block(user_msg: str, bot_response: str) -> str:
    """Cerebras cevabına Wikipedia bloğu ekle (uygunsa).

    Returns: "" (eklemeyecekse) veya "\n\n📚 Wikipedia: ..." bloğu.

    25.43-WIKI-GUARD (Neo bot self-critique 11 May): Render URL içeren
    cevaplarda Wiki injection ATLA — render cevap zaten görsel/zengin,
    Wiki ekleme alakasız konu (Eyotek → Belfort Üniversitesi tarzı) riski.
    """
    # GUARD: Render artifact cevaplarında wiki ekleme
    if bot_response and "api.fermategitimkurumlari.com/render/" in bot_response:
        return ""

    # Whitelist: sadece akademik konularda
    topic = _detect_wiki_topic(user_msg, bot_response)
    if not topic:
        return ""

    # 25.43 ek koruma — kurum-içi teknik terim Wiki'ye gitmesin
    BLOCKED_TOPICS = {
        "eyotek", "fermat", "fermatai", "blueprint", "three", "three.js",
        "ngrok", "supabase", "redis", "cerebras", "groq", "anthropic",
        "neo", "zeki", "duygu", "mahsum", "orsel", "bilge", "murathan",
    }
    topic_lower = topic.lower().strip()
    if any(b in topic_lower for b in BLOCKED_TOPICS):
        return ""

    # Cerebras cevabında zaten Wikipedia bahsi varsa duplicate önle
    if "wikipedia" in bot_response.lower():
        return ""

    try:
        from external_apis_v2 import wiki_lookup
        result = await wiki_lookup(topic)
        if not result.get("success"):
            return ""

        extract = (result.get("extract") or "").strip()
        if not extract or len(extract) < 80:
            return ""  # Çok kısa extract — değer yok

        # 250 char ile kes (cevap uzamasın)
        if len(extract) > 250:
            extract = extract[:250].rsplit(" ", 1)[0] + "..."

        url = result.get("url", "")
        block = f"\n\n📚 *Wikipedia — {result.get('title', topic)}:*\n_{extract}_"
        if url:
            block += f"\n🔗 {url}"
        return block
    except Exception as e:
        logger.debug(f"[WIKI_INJECT] fail: {e}")
        return ""
