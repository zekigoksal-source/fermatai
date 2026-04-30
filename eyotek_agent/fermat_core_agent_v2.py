"""
FermatCoreAgentV2 — Kapı 6 / Brief #4 + #5 (Oturum 25.29-30)
=============================================================

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
# Brief #5 — müdahale handler'ları (wrong_route, low_rag_score, frustration)
from signal_handlers import handle_wrong_route, handle_low_rag_score, handle_frustration


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
        # Brief #5 — müdahale state'i
        self._escalation_flag: bool = False           # crisis sinyali → True
        self._stats: dict = {"quality_events": []}    # quality_feedback geçmişi
        self._context_cache: dict = {}                # context_check phone→context map
        # v2 subscriber'larını kur (kendi davranışına geri etki için)
        self._setup_subscribers()
        logger.info("[V2] FermatCoreAgentV2 init — v1 inherit, bus subscribed (handlers v5)")

    def _setup_subscribers(self):
        """Bus'a kendi callback'lerini ekle.

        Brief #4: crisis, quality, context (log + state).
        Brief #5: wrong_route, low_rag_score, frustration (müdahale handler'ları).
        """
        # Brief #4 — gözlem
        self.bus.subscribe("crisis_signal", self._on_crisis_signal)
        self.bus.subscribe("quality_feedback", self._on_quality_feedback)
        self.bus.subscribe("context_check", self._on_context_check)
        # Brief #5 — müdahale (lambda ile self'i pass eder, async handler döner)
        self.bus.subscribe("wrong_route", lambda d: handle_wrong_route(d, self))
        self.bus.subscribe("low_rag_score", lambda d: handle_low_rag_score(d, self))
        self.bus.subscribe("frustration", lambda d: handle_frustration(d, self))
        logger.debug("[V2] subscriber'lar kuruldu (crisis, quality, context, wrong_route, low_rag_score, frustration)")

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

        Brief #6: quality_feedback sonrası self._last_rag_score < 0.3 ise
        low_rag_score sinyali yay (handler retry tetikleyecek).
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

            # Brief #6: RAG skoru düşükse retry sinyali yay
            try:
                rag_score = getattr(self, "_last_rag_score", None)
                if rag_score is not None and rag_score < 0.3:
                    await self.bus.emit(
                        "low_rag_score",
                        {
                            "query": (user_input or "")[:120],
                            "score": float(rag_score),
                            "attempt": 1,
                        },
                        actor_phone=caller_phone,
                    )
                    logger.info(f"[V2] low_rag_score emit: score={rag_score:.3f}")
            except Exception as _rag_e:
                logger.debug(f"[V2] low_rag_score check hata: {_rag_e}")
        except Exception as e:
            logger.debug(f"[V2] quality_feedback emit fail: {e}")
        self._last_post_flight = result
        return result

    # ─── SIGNAL HANDLERS (subscribe'lı callback'ler) ─────────────────────

    def _on_crisis_signal(self, signal: dict) -> None:
        """Crisis pattern algılandı.

        Brief #5: escalation_flag=True → run() sonrası inspection için.
        Yarın müdahale: Claude override, 112/182 inject, rehber bildirim.
        """
        payload = signal.get("payload", {})
        actor = signal.get("actor_phone", "")
        logger.warning(f"[V2-CRISIS] phone={actor[-4:] if actor else '?'}, payload={payload}")
        logger.critical(f"CRISIS: {signal}")
        self._escalation_flag = True

    def _on_quality_feedback(self, signal: dict) -> None:
        """Quality_log periyodik tarama sonucunda gelen feedback.

        Brief #5: stats geçmişine ekle (analiz için).
        Müdahale planı: Grade C/D dominantsa Cerebras → Claude'a yönlendir.
        """
        self._stats["quality_events"].append(signal)

    def _on_context_check(self, signal: dict) -> None:
        """Context drift / RAG kalitesi sinyali.

        Brief #5: payload['context'] varsa phone bazlı cache.
        Müdahale planı: RAG hit_score < 0.3 ise yeniden sorgula (low_rag_score emit).
        """
        payload = signal.get("payload") or {}
        phone = signal.get("actor_phone") or payload.get("phone", "")
        context = payload.get("context")
        if phone and context is not None:
            self._context_cache[phone] = context

    # ─── BRIEF #6 — MÜDAHALE METODLARI (signal_handlers.py çağırır) ────────

    async def _override_route(self, suggested: str) -> None:
        """wrong_route sinyali → bir sonraki run'da route override.

        signal_handlers.handle_wrong_route() bunu çağırır.
        run() sırasında self._forced_route'u kontrol etmek üst akışın işi
        (şu an sadece state set + log; routing_engine entegrasyonu ileride).
        """
        try:
            self._forced_route = suggested
            logger.info(f"[V2] route override aktif: {suggested}")
        except Exception as e:
            logger.warning(f"[V2] _override_route hata: {e}")

    async def _retry_rag(self, query: str = "", attempt: int = 1) -> None:
        """low_rag_score sinyali → RAG yeniden sorgu (max 2 attempt).

        Şu an log + state takibi. Gerçek rag_engine.retry_query çağrısı
        ileride; şimdilik attempt counter + retry threshold kontrolü.
        """
        try:
            attempt = int(attempt or 1)
            if attempt > 2:
                logger.debug(f"[V2] retry_rag max attempt asildi ({attempt}), skip")
                return
            self._last_rag_retry = {"query": (query or "")[:120],
                                      "attempt": attempt,
                                      "ts": time.time()}
            logger.info(f"[V2] RAG retry attempt={attempt} query='{str(query)[:60]}'")
        except Exception as e:
            logger.warning(f"[V2] _retry_rag hata: {e}")

    async def _adjust_tone(self, phone: str = "", tone: str = "empathic") -> None:
        """frustration sinyali → ton ayarı + (escalation_flag varsa) Kardelen'e bildir.

        signal_handlers.handle_frustration() bunu çağırır.
        Ton override sonraki cevaplarda kullanılabilir (system prompt eki).
        Eğer crisis flag aktif ise rehbere yönlendirme tetiklenir.
        """
        try:
            self._tone_override = tone or "empathic"
            logger.info(f"[V2] tone override: {self._tone_override} phone={phone[-4:] if phone else '?'}")
            if self._escalation_flag:
                await self._escalate_to_kardelen(phone)
        except Exception as e:
            logger.warning(f"[V2] _adjust_tone hata: {e}")

    async def _escalate_to_kardelen(self, phone: str = "") -> None:
        """Crisis tespit → rehber öğretmen Kardelen'e yönlendirme.

        ⚠️ NEO KURALI (KALICI): Onaysız WP/SMS/email YASAK. Bu metod
        sadece DB INSERT + log yapar. send_whatsapp_message ÇAĞRILMAZ
        (ENV flag KARDELEN_WP_NOTIFY_ENABLED=false default).
        Neo "ac" diyene kadar dış mesaj gönderilmez.

        Adımlar (her biri ayrı try/except):
          (a) DB'den öğrenciyi bul (phone → soz_no, full_name)
          (b) counsellor_notes tablosuna INSERT (rehberlik kayıt)
          (c) ACL'den Kardelen'in phone'unu çek (görselleme için)
          (d) WP bildirim → DISABLED (Neo onayı bekleniyor)
          (e) self._escalation_flag = False (tek seferlik trigger)
        """
        import os
        student_info = None
        kardelen_phone = None

        # (a) DB'den öğrenciyi bul
        try:
            from db_pool import db_fetchrow
            student_info = await db_fetchrow(
                """SELECT soz_no, full_name FROM students
                   WHERE REPLACE(COALESCE(phone, ''), '+', '') = $1
                   LIMIT 1""",
                (phone or "").replace("+", ""),
            )
            if student_info:
                logger.info(f"[V2-ESCALATE] (a) öğrenci bulundu: "
                            f"{student_info['full_name']} (soz_no={student_info['soz_no']})")
        except Exception as e:
            logger.warning(f"[V2-ESCALATE] (a) öğrenci sorgu hata: {e}")

        # (b) counsellor_notes INSERT (rehberlik kayıt)
        # Gerçek schema: soz_no, ogrenci_adi, ogrenci_soyadi, ogretmen, gorusme_tarihi,
        # not_turu, gorusulen, gorusme_turu, not_metni
        try:
            from db_pool import get_pool
            pool = await get_pool()
            soz_no = (student_info or {}).get("soz_no") if student_info else None
            full_name = (student_info or {}).get("full_name", "") if student_info else ""
            # Ad+soyad ayrımı (full_name → first/last)
            parts = (full_name or "").strip().split(maxsplit=1)
            ad = parts[0] if parts else ""
            soyad = parts[1] if len(parts) > 1 else ""
            note_text = (
                f"[Otomatik Bot Eskalasyonu — Kapı 6 V2] Crisis sinyal tespit edildi. "
                f"Phone: ***{phone[-4:] if phone else '?'}, isim: {full_name or 'bilinmiyor'}. "
                f"Bot frustration + escalation_flag birlikte tetiklendi. "
                f"Rehber kontrolü önerilir."
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO fermat.counsellor_notes
                       (soz_no, ogrenci_adi, ogrenci_soyadi, ogretmen,
                        gorusme_tarihi, not_turu, gorusme_turu, not_metni)
                       VALUES ($1, $2, $3, 'FermatAI Bot V2',
                               NOW(), 'kriz_alarmi', 'bot_otomatik', $4)
                       ON CONFLICT (soz_no, gorusme_tarihi, ogretmen) DO NOTHING""",
                    soz_no, ad, soyad, note_text,
                )
            logger.info(f"[V2-ESCALATE] (b) counsellor_notes INSERT OK (soz_no={soz_no})")
        except Exception as e:
            logger.warning(f"[V2-ESCALATE] (b) counsellor_notes hata: {e}")

        # (c) ACL'den Kardelen'in phone'unu çek (sadece referans, mesaj göndermek için DEĞİL)
        try:
            from db_pool import db_fetchval
            kardelen_phone = await db_fetchval(
                """SELECT phone FROM fermat.acl_users
                   WHERE full_name ILIKE '%Kardelen%' AND is_active = TRUE
                   LIMIT 1"""
            )
            if kardelen_phone:
                logger.info(f"[V2-ESCALATE] (c) Kardelen phone tespit edildi: ***{kardelen_phone[-4:]}")
        except Exception as e:
            logger.warning(f"[V2-ESCALATE] (c) Kardelen ACL sorgu hata: {e}")

        # (d) WP bildirim — KAPALI (Neo'nun kuralı: onaysız dış mesaj YASAK)
        wp_notify_enabled = os.getenv("KARDELEN_WP_NOTIFY_ENABLED", "false").lower() == "true"
        if wp_notify_enabled and kardelen_phone:
            try:
                # Sadece flag açıksa: gerçek mesaj gönder
                from secure_messenger import send_wp_message
                await send_wp_message(
                    to=kardelen_phone,
                    message=(
                        f"🚨 *Bot Eskalasyon Bildirimi*\n\n"
                        f"Öğrenci: {(student_info or {}).get('full_name', 'bilinmiyor')}\n"
                        f"Telefon: ***{phone[-4:] if phone else '?'}\n\n"
                        f"Bot crisis pattern + frustration tespit etti. "
                        f"Rehberlik kaydı düşürüldü, kontrol önerilir.\n\n"
                        f"_Otomatik Kapı 6 V2 eskalasyonu_"
                    ),
                    reason="bot_v2_kapi6_escalate",
                )
                logger.warning(f"[V2-ESCALATE] (d) Kardelen'e WP bildirim GÖNDERİLDİ")
            except Exception as e:
                logger.warning(f"[V2-ESCALATE] (d) WP gönderim hata: {e}")
        else:
            logger.info(
                f"[V2-ESCALATE] (d) WP bildirim SKIP "
                f"(KARDELEN_WP_NOTIFY_ENABLED=false — Neo onayı bekliyor)"
            )

        # (e) escalation_flag sıfırla (tek seferlik trigger, spam önleme)
        try:
            self._escalation_flag = False
            logger.info(f"[V2-ESCALATE] (e) escalation_flag sıfırlandı")
        except Exception as e:
            logger.warning(f"[V2-ESCALATE] (e) flag reset hata: {e}")

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
