"""
signal_handlers.py — FermatCoreAgentV2 sinyal handler'ları
============================================================

Kapı 6 / Brief #5 (Oturum 25.30) — V2 agent'ın LiveSignalBus üzerinden
aldığı 3 müdahale sinyaline karşılık gelen async handler fonksiyonları.

Sinyaller:
  - wrong_route    → route override (suggested_route)
  - low_rag_score  → RAG yeniden sorgu (query, attempt)
  - frustration    → ton/route ayarı (phone, tone='empathic')

Bus signal formatı:
  {"type": ..., "payload": {...}, "actor_phone": "...", "created_at": "..."}

Handler'lar payload'u öncelikle signal_data'dan okur, yoksa
signal_data["payload"]'a düşer (geri uyumluluk).
"""
from __future__ import annotations
from typing import Any

from loguru import logger


def _extract(signal_data: dict, key: str, default: Any = None) -> Any:
    """Önce top-level, sonra payload içinden key oku (geri uyumlu)."""
    if not isinstance(signal_data, dict):
        return default
    if key in signal_data:
        return signal_data.get(key)
    payload = signal_data.get("payload")
    if isinstance(payload, dict):
        return payload.get(key, default)
    return default


async def handle_wrong_route(signal_data: dict, agent) -> None:
    """Route override: signal_data['suggested_route'] varsa agent._override_route() çağır."""
    suggested = _extract(signal_data, "suggested_route")
    if suggested:
        logger.info(f"[SH] wrong_route → override: {suggested}")
        if hasattr(agent, "_override_route"):
            try:
                await agent._override_route(suggested)
            except Exception as e:
                logger.warning(f"[SH] _override_route hata: {e}")


async def handle_low_rag_score(signal_data: dict, agent) -> None:
    """RAG retry: agent._retry_rag(query, attempt) çağır."""
    query = _extract(signal_data, "query", "") or ""
    attempt = _extract(signal_data, "attempt", 1) or 1
    logger.info(f"[SH] low_rag_score → retry RAG query='{str(query)[:60]}' attempt={attempt}")
    if hasattr(agent, "_retry_rag"):
        try:
            await agent._retry_rag(query=query, attempt=attempt)
        except Exception as e:
            logger.warning(f"[SH] _retry_rag hata: {e}")


async def handle_frustration(signal_data: dict, agent) -> None:
    """Ton/route ayarı: agent._adjust_tone(phone, tone='empathic') çağır."""
    phone = _extract(signal_data, "phone", "") or signal_data.get("actor_phone", "") if isinstance(signal_data, dict) else ""
    masked = phone[-4:] if phone else "?"
    logger.info(f"[SH] frustration → adjust tone empathic phone={masked}")
    if hasattr(agent, "_adjust_tone"):
        try:
            await agent._adjust_tone(phone, tone="empathic")
        except Exception as e:
            logger.warning(f"[SH] _adjust_tone hata: {e}")
