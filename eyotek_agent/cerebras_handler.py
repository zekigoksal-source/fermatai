"""
Cerebras AI Handler (Oturum 25.22)
=====================================

Cerebras Pay-as-You-Go entegrasyonu — Groq'un yerine geçer.

Modeller:
- llama3.1-8b           — classify (323ms, basit)
- gpt-oss-120b          — kavramsal + plan (436ms, sweet spot, KVKK 3/3 reddetti)
- qwen-3-235b...2507    — kompleks plan + analiz (567ms, en kaliteli)

Maliyet (estimate, gerçek pricing kullanım sonrası belli olur):
- llama3.1-8b: ~$0.10/1M token
- gpt-oss-120b: ~$0.30-0.50/1M
- qwen-3-235b: ~$0.60-1/1M

Karşılaştırma:
- Claude Sonnet: $3 in / $15 out (5-30x daha pahalı)
- Groq Llama 3.3 70B: $0.59 in / $0.79 out (Cerebras paid kapalı)

API: OpenAI-compatible (https://api.cerebras.ai/v1)

KVKK GÜVENLİK:
- llama3.1-8b → injection saldırısında SIZINTI yapabildi (1/3)
- gpt-oss-120b → 3/3 saldırı reddetti
- qwen-3-235b → 3/3 saldırı reddetti
=> classify dışında llama3.1-8b kullanma. Üst tier gerekirse gpt-oss veya qwen.
"""
from __future__ import annotations
import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Model katalog
CEREBRAS_MODELS = {
    "classify": "llama3.1-8b",
    "kavramsal": "gpt-oss-120b",
    "kompleks": "qwen-3-235b-a22b-instruct-2507",
}

# Tier (intent → model) eşleştirme
INTENT_TO_MODEL = {
    # Hızlı + basit
    "selamlama":         "llama3.1-8b",
    "veda":              "llama3.1-8b",
    "tesekkur":          "llama3.1-8b",
    "yks_takvim":        "llama3.1-8b",  # statik bilgi (fast'tan kaçanlar)
    "mufredat_bilgi":    "llama3.1-8b",
    "kurum_bilgi":       "llama3.1-8b",
    # Kavramsal + plan (gpt-oss-120b sweet spot)
    "kavram_aciklama":   "gpt-oss-120b",
    "ornek_iste":        "gpt-oss-120b",
    "cozum_iste":        "gpt-oss-120b",
    "ozet_iste":         "gpt-oss-120b",
    "yontem_iste":       "gpt-oss-120b",
    "motivasyon_destek": "gpt-oss-120b",
    "duygu_paylasim":    "gpt-oss-120b",
    "uretim_paylas":     "gpt-oss-120b",
    "yetenek_sorgu":     "gpt-oss-120b",
    "meta_direktif":     "gpt-oss-120b",
    # Karmaşık plan/analiz/kavramsal — qwen daha akademik
    # NOT: Bunlar Claude tool gerektirebilir, classifier üst kontrolü ile
    "plan_yap":          "qwen-3-235b-a22b-instruct-2507",
    "analiz_iste":       "qwen-3-235b-a22b-instruct-2507",
    "deneme_analiz":     "qwen-3-235b-a22b-instruct-2507",
    "hedef_analiz":      "qwen-3-235b-a22b-instruct-2507",
    # 25.40o (Neo direktif): qwen-3-235b içerik üretim BÜYÜK potansiyel
    # 95 konu Claude $4/100sn → 211 konu qwen $0.20/3sn (33x hız, %95 ucuz, EŞDEĞER kalite)
    # Bu intent'ler Claude yerine qwen'e gitmeli — proaktif yetkinlik kullanımı
    "test_olusturma":    "qwen-3-235b-a22b-instruct-2507",  # "test hazırla", "konu tarama"
    "soru_uret":         "qwen-3-235b-a22b-instruct-2507",  # "soru üret/yaz", "X soru hazırla"
    "yeni_nesil_uret":   "qwen-3-235b-a22b-instruct-2507",  # "yeni nesil/maarif sorusu"
    "icerik_uretim":     "qwen-3-235b-a22b-instruct-2507",  # "metni hazırla", "döküman", "etkinlik"
    "konu_anlatim_uzun": "qwen-3-235b-a22b-instruct-2507",  # "X konusunu detaylı anlat"
    "ornek_paket_uret":  "qwen-3-235b-a22b-instruct-2507",  # "5 örnek üret", "alıştırma"
    "karsilastirma":     "qwen-3-235b-a22b-instruct-2507",  # "X vs Y" iki kavram/konu kıyas
    "ozet_uzun":         "qwen-3-235b-a22b-instruct-2507",  # detaylı özet (kısa özet → ozet_iste/120b)
    "metin_zenginlestir":"qwen-3-235b-a22b-instruct-2507",  # RAG'den gelen ham içeriği güzel sun
    # Hassas — buralara HİÇ gelmemeli (Claude'a giderler)
    # injection_suspect, hassas_veri, finans, role_change, baska_ogrenci
}


# ═══════════════════════════════════════════════════════════════════
# Brief #11 (Neo 1 May 25.37) — INTENT → RENDERER MAP
# Cerebras 120b/235b modelleri channel='web' geldiğinde hangi
# renderer'ı kullanacağını net bilsin diye system_prompt'a inject edilir.
# ═══════════════════════════════════════════════════════════════════
INTENT_RENDERER_MAP: dict[str, list[str]] = {
    "kavram_aciklama":   ["formula", "steps", "quiz"],
    "cozum_iste":        ["steps", "formula"],
    "ornek_iste":        ["steps", "compare2"],
    "ozet_iste":         ["steps", "kgraph"],
    "karsilastirma":     ["compare2"],
    "deneme_analiz":     ["chart", "radar", "karne"],
    "analiz_iste":       ["chart", "radar"],
    "hedef_analiz":      ["gauge", "progress", "timeline"],
    "plan_yap":          ["timeline", "kgraph", "progress"],
    "mufredat_bilgi":    ["progress", "karne"],
    # 25.40o (Neo direktif) — yeni icerik uretim renderer eslestirmeleri
    # "Goresel anlamda premium kalitede icerik aktariyor olalim, sadece duz yazi degil"
    "test_olusturma":    ["quiz", "steps", "chart"],         # interaktif quiz + adim adim
    "soru_uret":         ["quiz", "steps"],                   # quiz card + cozum adimlari
    "yeni_nesil_uret":   ["quiz", "compare2", "chart"],       # quiz + karsi-ornek + grafik
    "icerik_uretim":     ["formula", "steps", "kgraph"],      # formul + adim + kavram haritasi
    "konu_anlatim_uzun": ["formula", "steps", "kgraph", "quiz"], # tam paket
    "ornek_paket_uret":  ["quiz", "compare2", "steps"],       # 5 ornek paket
    "ozet_uzun":         ["steps", "kgraph", "timeline"],     # zenginlestirilmis ozet
    "metin_zenginlestir":["formula", "steps"],                # RAG icerik + gorsel
    # Renderer YOK — bu intent'lerde sadece sıcak metin
    "motivasyon_destek": [],
    "duygu_paylasim":    [],
    "selamlama":         [],
    "veda":              [],
    "tesekkur":          [],
}


def get_renderer_hint(intent: str, channel: str) -> str:
    """Brief #11 — channel='web' VE intent eşleşirse renderer hint döndür.
    Cerebras system_prompt'una inject edilir, modele renderer kullanmasını söyler.

    Args:
        intent: prompt_tiers/intent_classifier'dan gelen intent etiketi
        channel: 'web' | 'whatsapp' | 'agent_api' | 'cli'
    Returns:
        Inject edilecek string (boş string = renderer yok)
    """
    if channel != "web":
        return ""
    renderers = INTENT_RENDERER_MAP.get(intent, [])
    if not renderers:
        return ""
    r_str = " + ".join(f"```{r}" for r in renderers)
    return (
        f"\n\n🎨 [RENDERER — ZORUNLU KULLAN]: {r_str}\n"
        f"Bu intent ({intent}) için web kanalında bu renderer'lar olmadan cevap KABUL EDİLMEZ.\n"
        f"Düz metin + markdown tablo YETERSİZ.\n"
    )


class CerebrasClient:
    """OpenAI SDK üzerinden Cerebras API."""

    def __init__(self):
        self.api_key = os.getenv("CEREBRAS_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("CEREBRAS_API_KEY env'de yok")
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.cerebras.ai/v1",
                timeout=20.0,  # Cerebras hızlı, 20s yeter
            )
            logger.info("Cerebras hazir: 3 model erisilebilir")
        except ImportError:
            raise RuntimeError("openai package gerekli (pip install openai)")

    def complete(
        self,
        messages: list,
        system: Optional[str] = None,
        model: str = "gpt-oss-120b",
        max_tokens: int = 1500,
        temperature: float = 0.3,
        intent: Optional[str] = None,
        channel: str = "whatsapp",
    ) -> dict:
        """Sync chat completion. Returns {text, model, usage, ms}.

        Brief #11 (1 May 25.37): channel='web' + intent eşleşirse
        renderer_hint otomatik system prompt'a inject edilir.
        """
        # Brief #11 — Renderer hint inject (web + tanımlı intent'te)
        if intent and channel:
            try:
                renderer_hint = get_renderer_hint(intent, channel)
                if renderer_hint:
                    system = (system or "") + renderer_hint
            except Exception:
                pass

        # 25.41 (Neo 9 May) — Keyword-based renderer hint inject (fallback)
        # Intent eşleşmese bile son user mesajından keyword tetikleme:
        # "grafik göster" / "kıyasla" / "trend" → chart/compare2 SERT direktif
        if channel == "web" and messages:
            try:
                last_user = ""
                for m in reversed(messages):
                    if m.get("role") == "user":
                        c = m.get("content", "")
                        if isinstance(c, list):
                            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
                        last_user = str(c)
                        break
                if last_user:
                    from renderer_hint_inject import build_hint
                    kw_hint = build_hint(last_user, channel="web")
                    if kw_hint:
                        system = (system or "") + kw_hint
            except Exception:
                pass

        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        # Claude format → OpenAI format normalize
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                # Anthropic content blocks
                text_parts = [
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)
            if isinstance(content, str) and content.strip():
                msgs.append({"role": m.get("role", "user"), "content": content})

        t0 = time.time()
        try:
            r = self.client.chat.completions.create(
                model=model,
                messages=msgs,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            ms = int((time.time() - t0) * 1000)
            return {
                "text": r.choices[0].message.content or "",
                "model": model,
                "ms": ms,
                "tokens_in": r.usage.prompt_tokens,
                "tokens_out": r.usage.completion_tokens,
                "ok": True,
            }
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            logger.warning(f"Cerebras {model} hata: {str(e)[:200]}")
            return {
                "text": "",
                "model": model,
                "ms": ms,
                "ok": False,
                "error": str(e)[:300],
            }

    def complete_with_tools(
        self,
        messages: list,
        tools: list,
        model: str = "qwen-3-235b-a22b-instruct-2507",
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> dict:
        """OpenAI-format tool-calling.

        Args:
            messages: OpenAI format mesaj listesi (system dahil)
            tools: OpenAI tool schema listesi [{type, function: {name, description, parameters}}]

        Returns:
            {text, tool_calls: [{id, name, arguments}], model, ms, ok}
        """
        t0 = time.time()
        try:
            r = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            ms = int((time.time() - t0) * 1000)
            msg = r.choices[0].message
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    })
            return {
                "text": msg.content or "",
                "tool_calls": tool_calls,
                "model": model,
                "ms": ms,
                "tokens_in": r.usage.prompt_tokens if r.usage else 0,
                "tokens_out": r.usage.completion_tokens if r.usage else 0,
                "ok": True,
            }
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            logger.warning(f"Cerebras {model} tool-calling hata: {str(e)[:200]}")
            return {
                "text": "",
                "tool_calls": [],
                "model": model,
                "ms": ms,
                "ok": False,
                "error": str(e)[:300],
            }

    async def complete_with_tools_async(
        self,
        messages: list,
        tools: list,
        model: str = "qwen-3-235b-a22b-instruct-2507",
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> dict:
        """Async wrapper for complete_with_tools."""
        import asyncio
        return await asyncio.to_thread(
            self.complete_with_tools,
            messages=messages, tools=tools, model=model,
            max_tokens=max_tokens, temperature=temperature,
        )

    async def complete_async(
        self,
        messages: list,
        system: Optional[str] = None,
        model: str = "gpt-oss-120b",
        max_tokens: int = 1500,
        temperature: float = 0.3,
        intent: Optional[str] = None,
        channel: str = "whatsapp",
    ) -> dict:
        """Async wrapper — asyncio.to_thread ile sync client'i sar.

        Brief #11 (1 May 25.37): intent + channel param eklendi → renderer_hint inject.
        """
        import asyncio
        return await asyncio.to_thread(
            self.complete,
            messages=messages, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
            intent=intent, channel=channel,
        )


def select_cerebras_model(intent: Optional[str], channel: str = "whatsapp") -> str:
    """Intent + kanal'a göre uygun Cerebras modelini dön.

    Oturum 25.29 (Neo karari): WEB kanalinda kavramsal+ornek+aciklama tipi
    sorularda qwen-3-235b kullan — ogrenci'nin Claude tarzi detayli + akademik
    cevap aldigi hisseti vermek icin. WP'de hizli olsun diye gpt-oss-120b kalsin.
    """
    if not intent:
        # Kanal bazli default
        if channel == "web":
            return CEREBRAS_MODELS["kompleks"]  # qwen-3-235b
        return CEREBRAS_MODELS["kavramsal"]  # gpt-oss-120b

    # Web kanalinda kavramsal/ornek/aciklama → qwen 235b (akademik kalite)
    if channel == "web":
        WEB_UPGRADE_INTENTS = {
            "kavram_aciklama", "ornek_iste", "cozum_iste",
            "ozet_iste", "yontem_iste", "duygu_paylasim",
            "motivasyon_destek", "uretim_paylas",
        }
        if intent in WEB_UPGRADE_INTENTS:
            return CEREBRAS_MODELS["kompleks"]  # qwen-3-235b

    return INTENT_TO_MODEL.get(intent, CEREBRAS_MODELS["kavramsal"])


# KVKK güvenlik: llama3.1-8b sadece BASİT classify için
# Hassas bir intent ile asla 8b kullanma
HASSAS_INTENTS = {
    "injection_suspect", "hassas_veri", "finans",
    "role_change", "admin_action", "baska_ogrenci",
}


def is_safe_for_cerebras(intent: Optional[str]) -> bool:
    """Hassas intent ise Cerebras kullanma → Claude'a yönlendir."""
    if not intent:
        return True  # bilinmiyor, yine de Cerebras dener
    return intent not in HASSAS_INTENTS
