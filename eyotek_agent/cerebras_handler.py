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
    # Hassas — buralara HİÇ gelmemeli (Claude'a giderler)
    # injection_suspect, hassas_veri, finans, role_change, baska_ogrenci
}


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
    ) -> dict:
        """Sync chat completion. Returns {text, model, usage, ms}."""
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

    async def complete_async(
        self,
        messages: list,
        system: Optional[str] = None,
        model: str = "gpt-oss-120b",
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> dict:
        """Async wrapper — asyncio.to_thread ile sync client'i sar."""
        import asyncio
        return await asyncio.to_thread(
            self.complete,
            messages=messages, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
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
