"""
FermatCoreAgentV2 — Kapı 6 / Brief #4 (Oturum 25.29)
======================================================

V1 agent'a DOKUNMADAN paralel çalışan v2.
LiveSignalBus'a subscribe olur, mesaj işlenirken anlık sinyal yayar
ve müdahale edebilir.

İSKELET — bu commit'te canlı introspection altyapısı kuruldu, gerçek
müdahale mantığı (RAG retry, route override, frustration intercept) sonraki
oturumlarda eklenir. Şu an v2 v1 ile aynı şekilde cevaplar AMA işlemi
sinyal/log ile zenginleştirir.

Strateji B (production'a dokunma):
  whatsapp_bridge.py'deki AGENT_V2_PHONES = {neo} setine bağlı.
  Sadece Neo'nun WhatsApp hattında v2 aktif, diğer 124 öğrenci v1'de.
  Rollback: AGENT_V2_PHONES = set() — tek satır, anında.

Mimari:
  ┌─ v1 (FermatCoreAgent) ─────────────────────┐
  │ run() → tool dispatch → Claude → cevap     │
  └────────────────────────────────────────────┘
       ↓ inherit
  ┌─ v2 (FermatCoreAgentV2) ───────────────────┐
  │ pre_flight_check() → bus.emit('pre_route')│
  │ run() → super().run() (v1 davranışı)      │
  │ post_flight_log() → quality_log oku       │
  │                                            │
  │ on_signal() → v1'in başlattığı sinyallere │
  │   tepki ver (subscribe ile)               │
  └────────────────────────────────────────────┘

İlk kazanım: bot'un kendisi her mesajda hangi katmanlardan geçtiğini
canlı görür (live_signals tablosu). İkinci aşama: müdahale (yarın).
"""
from __future__ import annotations
import asyncio
import time
from typing import Optional

from loguru import logger

from fermat_core_agent import FermatCoreAgent
from live_signal_bus import get_bus, KNOWN_SIGNAL_TYPES


class FermatCoreAgentV2(FermatCoreAgent):
    """V1'i extend eder, run() öncesi/sonrası canlı sinyal yayar.

    Mevcut v1 davranışı 100% korunur. v2 sadece introspection katmanı ekler.
    """

    def __init__(self):
        super().__init__()
        self.bus = get_bus()
        self.v2_run_count = 0
        self._last_pre_flight: Optional[dict] = None
        self._last_post_flight: Optional[dict] = None
        # v2 subscriber'larını kur (kendi davranışına geri etki için)
        self._setup_subscribers()
        logger.info("[V2] FermatCoreAgentV2 init — v1 inherit, bus subscribed")

    def _setup_subscribers(self):
        """Bus'a kendi callback'lerini ekle.

        Şu an sadece log alır — müdahale mantığı (yarın) on_signal() ile gelecek.
        """
        self.bus.subscribe("crisis_signal", self._on_crisis_signal)
        self.bus.subscribe("quality_feedback", self._on_quality_feedback)
        self.bus.subscribe("context_check", self._on_context_check)
        logger.debug("[V2] subscriber'lar kuruldu (crisis, quality, context)")

    # ─── PRE-FLIGHT (cevap üretilmeden ÖNCE) ─────────────────────────────

    async def pre_flight_check(self, user_input: str, caller_phone: str,
                                channel: str = "whatsapp") -> dict:
        """Mesaj işlenmeden önce kontrol.

        - LiveSignalBus'a 'pre_route' sinyali emit eder
        - Crisis pattern check (basit keyword tarama, fast)
        - Context drift kontrolü (basit, şimdilik sadece log)

        Returns:
            {checks_run, crisis_detected, signal_id}
        """
        result = {"checks_run": 0, "crisis_detected": False, "signal_id": None}

        # 1. pre_route sinyali yay (subscribe'lılar route kararı verilmeden tepki ver)
        try:
            r = await self.bus.emit(
                "pre_route",
                {
                    "user_input_preview": (user_input or "")[:200],
                    "channel": channel,
                    "v2_run": self.v2_run_count,
                },
                actor_phone=caller_phone,
                ttl_seconds=300,
            )
            result["signal_id"] = r.get("signal_id")
            result["checks_run"] += 1
        except Exception as e:
            logger.debug(f"[V2] pre_route emit fail: {e}")

        # 2. Crisis pattern (hızlı keyword tarama — sentiment_tracker yarın eklenecek)
        try:
            crisis_keywords = (
                "intihar", "kendimi öldür", "yaşamak istemiyorum",
                "depresyon", "umut yok", "hayata son",
            )
            msg_lower = (user_input or "").lower()
            if any(k in msg_lower for k in crisis_keywords):
                result["crisis_detected"] = True
                await self.bus.emit(
                    "crisis_signal",
                    {"matched": True, "preview": msg_lower[:120]},
                    actor_phone=caller_phone,
                )
                result["checks_run"] += 1
        except Exception as e:
            logger.debug(f"[V2] crisis check fail: {e}")

        self._last_pre_flight = result
        return result

    # ─── POST-FLIGHT (cevap üretildikten sonra) ──────────────────────────

    async def post_flight_log(self, user_input: str, response: str,
                                caller_phone: str, ms: int = 0) -> dict:
        """Cevap üretildikten sonra log + quality_feedback emit.

        - quality_feedback sinyali (self_observer hook'u için altyapı)
        - response_length, ms, route_info DB'ye kaydedilir
        """
        result = {"signal_id": None}
        try:
            r = await self.bus.emit(
                "quality_feedback",
                {
                    "input_len": len(user_input or ""),
                    "response_len": len(response or ""),
                    "ms": ms,
                    "v2_run": self.v2_run_count,
                },
                actor_phone=caller_phone,
            )
            result["signal_id"] = r.get("signal_id")
        except Exception as e:
            logger.debug(f"[V2] quality_feedback emit fail: {e}")
        self._last_post_flight = result
        return result

    # ─── SIGNAL HANDLERS (subscribe'lı callback'ler) ─────────────────────

    def _on_crisis_signal(self, signal: dict) -> None:
        """Crisis pattern algılandı — şimdilik sadece log, yarın müdahale.

        Müdahale planı (yarın):
          - Claude'a override (fast_response yerine premium)
          - 112/182 destek hattı bilgisi cevaba inject
          - Rehber öğretmene WP bildirim
        """
        payload = signal.get("payload", {})
        actor = signal.get("actor_phone", "")
        logger.warning(f"[V2-CRISIS] phone={actor[-4:] if actor else '?'}, payload={payload}")

    def _on_quality_feedback(self, signal: dict) -> None:
        """Quality_log periyodik tarama sonucunda gelen feedback.

        Müdahale planı (yarın): Grade C/D dominantsa Cerebras → Claude'a yönlendir.
        """
        # Şimdilik sadece counter
        pass

    def _on_context_check(self, signal: dict) -> None:
        """Context drift / RAG kalitesi sinyali.

        Müdahale planı (yarın): RAG hit_score < 0.3 ise yeniden sorgula.
        """
        pass

    # ─── ANA RUN OVERRIDE ─────────────────────────────────────────────────

    async def run(self, user_input: str, caller_phone: str = "",
                   channel: str = "whatsapp", _stream_queue=None) -> str:
        """V1 run'ını sarar — pre/post flight ekler.

        v1 davranışı 100% korunur (super().run() çağırılır).
        v2 sadece etrafına bus emit ekler.
        """
        self.v2_run_count += 1
        t0 = time.time()

        # Pre-flight (cevap üretilmeden önce)
        try:
            await self.pre_flight_check(user_input, caller_phone, channel)
        except Exception as e:
            logger.warning(f"[V2] pre_flight hata (devam): {e}")

        # V1'in run() metodunu CHANGE without çağır — tüm akış aynen
        response = await super().run(
            user_input,
            caller_phone=caller_phone,
            channel=channel,
            _stream_queue=_stream_queue,
        )

        # Post-flight (cevap üretildikten sonra)
        try:
            ms = int((time.time() - t0) * 1000)
            await self.post_flight_log(user_input, response or "", caller_phone, ms=ms)
        except Exception as e:
            logger.warning(f"[V2] post_flight hata (devam): {e}")

        return response

    # ─── DEBUG / AUDIT ────────────────────────────────────────────────────

    def get_v2_stats(self) -> dict:
        """V2 ile ilgili anlık metrik (admin debug için)."""
        return {
            "v2_run_count": self.v2_run_count,
            "bus_stats": self.bus.get_stats(),
            "last_pre_flight": self._last_pre_flight,
            "last_post_flight": self._last_post_flight,
        }


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _smoke():
        print("=== FermatCoreAgentV2 smoke test ===")
        agent = FermatCoreAgentV2()
        print(f"  v2 instance: OK (count={agent.v2_run_count})")
        print(f"  inherit class: {agent.__class__.__bases__[0].__name__}")
        print(f"  bus: {agent.bus.__class__.__name__}")
        print(f"  bus stats: {agent.bus.get_stats()}")
        print()

        # Pre-flight test (Neo crisis pattern)
        print("=== pre_flight_check (normal) ===")
        r = await agent.pre_flight_check("merhaba", "905051256802")
        print(f"  result: {r}")
        print()

        print("=== pre_flight_check (crisis pattern) ===")
        r = await agent.pre_flight_check("intihar etmek istiyorum", "905051256802")
        print(f"  result: {r}")
        print(f"  crisis_detected: {r['crisis_detected']}")
        print()

        # Post-flight
        print("=== post_flight_log ===")
        r = await agent.post_flight_log("test soru", "test cevap", "905051256802", ms=120)
        print(f"  result: {r}")
        print()

        print(f"=== final v2 stats ===")
        print(agent.get_v2_stats())

    asyncio.run(_smoke())
