"""
Groq API Handler — FermatAI için Llama 3.3 70B inference

Yarın (25 Nisan) eyotek_agent/ altına kopyalanacak + llm_router.py'e entegre.

Kullanım:
    from groq_handler import GroqClient
    client = GroqClient()
    response = await client.complete(messages=[...], model="llama-3.3-70b-versatile")
"""
from __future__ import annotations
import os
import asyncio
from typing import Optional

try:
    from groq import Groq, AsyncGroq
except ImportError:
    Groq = None
    AsyncGroq = None

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# ─── Konfig ────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_PRIMARY = os.getenv("GROQ_MODEL_PRIMARY", "llama-3.3-70b-versatile")
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "llama-3.1-8b-instant")
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT_SEC", "30"))
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "2"))


class GroqClient:
    """Groq API için async wrapper — Claude'a benzer API."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or GROQ_API_KEY
        if not key:
            raise ValueError("GROQ_API_KEY .env'de bulunmuyor")
        if AsyncGroq is None:
            raise ImportError("pip install groq")
        self.client = AsyncGroq(api_key=key, timeout=GROQ_TIMEOUT, max_retries=GROQ_MAX_RETRIES)

    async def complete(
        self,
        messages: list[dict],
        model: str = GROQ_MODEL_PRIMARY,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> dict:
        """
        Groq API chat completion.

        Args:
            messages: OpenAI-format chat history [{"role": "user", "content": "..."}]
            model: "llama-3.3-70b-versatile" (kaliteli) veya "llama-3.1-8b-instant" (hızlı)
            max_tokens: Çıkış limiti
            temperature: 0.0 (belirgin) - 1.0 (yaratıcı)
            system: Sistem prompt (OpenAI uyumluluğu için)

        Returns:
            {
                "text": "...",
                "model": "...",
                "input_tokens": N,
                "output_tokens": N,
                "latency_ms": N,
                "finish_reason": "stop|length|..."
            }
        """
        import time
        t0 = time.time()

        # System prompt varsa messages'ın başına ekle
        if system:
            msgs = [{"role": "system", "content": system}] + messages
        else:
            msgs = messages

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=msgs,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            logger.warning(f"Groq API hatası: {e}")
            raise

        latency_ms = int((time.time() - t0) * 1000)
        choice = response.choices[0]
        usage = response.usage

        return {
            "text": choice.message.content or "",
            "model": response.model,
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "latency_ms": latency_ms,
            "finish_reason": choice.finish_reason,
        }

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str = GROQ_MODEL_PRIMARY,
        max_tokens: int = 2048,
        temperature: float = 0.3,  # tool-calling için düşük
    ) -> dict:
        """
        Tool-calling destekli completion.

        Llama 70B Claude kadar mükemmel olmasa da basit tool çağrıları için yeterli.
        Karmaşık multi-step için Claude'a fallback önerilir.
        """
        import time
        t0 = time.time()

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                tool_choice="auto",
            )
        except Exception as e:
            logger.warning(f"Groq tool-calling hatası: {e}")
            raise

        latency_ms = int((time.time() - t0) * 1000)
        choice = response.choices[0]
        usage = response.usage

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })

        return {
            "text": choice.message.content or "",
            "tool_calls": tool_calls,
            "model": response.model,
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "latency_ms": latency_ms,
            "finish_reason": choice.finish_reason,
        }


# ─── Maliyet hesabı ────────────────────────────────────────
# Groq fiyat tablosu (Nisan 2026 — regularly check https://groq.com/pricing)
GROQ_PRICES = {
    "llama-3.3-70b-versatile": {"in": 0.59, "out": 0.79},  # $/1M token
    "llama-3.1-8b-instant":    {"in": 0.05, "out": 0.08},
    "qwen-2.5-32b":            {"in": 0.79, "out": 0.79},
    "mixtral-8x7b-32768":      {"in": 0.24, "out": 0.24},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Mesaj başına $ maliyeti."""
    price = GROQ_PRICES.get(model)
    if not price:
        return 0.0
    return (input_tokens * price["in"] + output_tokens * price["out"]) / 1_000_000


# ─── Smoke test ────────────────────────────────────────────
async def smoke_test():
    """Groq bağlantısını test et."""
    client = GroqClient()
    result = await client.complete(
        messages=[{"role": "user", "content": "Merhaba, Türkçe bir öğrenciye 'kaldırma kuvvetini' 2 cümleyle açıkla."}],
        system="Sen yardımcı bir YKS fizik öğretmenisin. Kısa ve öz konuş.",
        max_tokens=200,
    )
    print(f"Model: {result['model']}")
    print(f"Latency: {result['latency_ms']}ms")
    print(f"Input: {result['input_tokens']} / Output: {result['output_tokens']} tokens")
    print(f"Maliyet: ${calculate_cost(result['model'], result['input_tokens'], result['output_tokens']):.6f}")
    print(f"\n{result['text']}")


if __name__ == "__main__":
    asyncio.run(smoke_test())
