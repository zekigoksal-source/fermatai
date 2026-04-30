"""
LiveSignalBus — Kapı 6 / Brief #4 (Oturum 25.29)
==================================================

Sistem retrospektif öz-gözlemden ANLIK introspeksyona geçiyor.

Felsefe (botla yapılan dev sohbeti, 29 Nis 23:48):
  Şu an  → Mesaj gelir → işlenir → biter → routing_stats yazılır → "ne oldu?" sonradan
  Kapı 6 → Mesaj gelir → işlenirken izlenir → "ne oluyor?" CANLI

Kullanım:
  bus = LiveSignalBus()
  bus.subscribe("crisis_signal", lambda sig: agent.intervene(sig))
  bus.emit("crisis_signal", {"pattern": "intihar", "phone": "905..."})
  # Subscribe'lı callback senkron çağrılır + DB'ye persist edilir (TTL=5dk)

Sinyal tipleri (Brief #4):
  - pre_route       — routing kararı VERILMEDEN önce (route'u durdurmak için)
  - post_route      — routing kararı verildikten sonra (sonradan ölçüm)
  - crisis_signal   — kriz pattern (intihar, depresyon) yakalandı
  - quality_feedback — quality_log'tan periyodik okuma
  - token_emit      — Claude/Cerebras'tan her token (streaming için, opsiyonel)
  - context_check   — context drift / RAG kalitesi anlık ölçümü

Mimari:
  In-memory: subscribers dict[type, list[callback]] — anlık dispatch
  DB persist: live_signals tablosu — sonradan denetim + audit + cross-process
  TTL flush: expires_at < NOW() olanları periyodik UPDATE consumed=TRUE
"""
from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, Any

from loguru import logger


# Süre limitleri
DEFAULT_TTL_SECONDS = 300  # 5 dakika

# Kabul edilen sinyal tipleri (whitelist — tipo koruması)
KNOWN_SIGNAL_TYPES = {
    "pre_route",
    "post_route",
    "crisis_signal",
    "quality_feedback",
    "token_emit",
    "context_check",
    # Brief #6 — müdahale sinyalleri
    "wrong_route",
    "low_rag_score",
    "frustration",
    # Test/debug için
    "test_signal",
}


class LiveSignalBus:
    """Singleton-friendly event bus.

    In-memory subscriber listesi + DB persistence.
    """

    _instance: Optional["LiveSignalBus"] = None

    def __new__(cls) -> "LiveSignalBus":
        # Singleton pattern: aynı process'te tek bus, tüm subscriber'lar paylaşır
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._subscribers: dict[str, list[Callable]] = {}
        self._stats: dict[str, int] = {"emitted": 0, "callbacks_run": 0,
                                        "callback_errors": 0, "db_writes": 0,
                                        "db_errors": 0}
        self._table_ensured = False  # ensure_table() bir kere çalışsın
        self._initialized = True
        logger.debug("[BUS] LiveSignalBus singleton initialized")

    async def ensure_table(self) -> bool:
        """live_signals tablosu yoksa oluştur (idempotent).

        Bridge start'ta veya ilk emit()'te çağrılır. Migration manuel
        koşmamış olsa bile bot çalışır. CREATE TABLE IF NOT EXISTS güvenli.
        """
        if self._table_ensured:
            return True
        try:
            from db_pool import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS fermat.live_signals (
                        id          SERIAL PRIMARY KEY,
                        created_at  TIMESTAMP DEFAULT NOW(),
                        expires_at  TIMESTAMP NOT NULL,
                        signal_type TEXT NOT NULL,
                        payload     JSONB,
                        actor_phone TEXT,
                        consumed    BOOLEAN DEFAULT FALSE,
                        consumed_at TIMESTAMP
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_live_signals_type_unconsumed
                    ON fermat.live_signals(signal_type, consumed) WHERE consumed = FALSE
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_live_signals_expires
                    ON fermat.live_signals(expires_at) WHERE consumed = FALSE
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_live_signals_actor
                    ON fermat.live_signals(actor_phone, created_at DESC)
                """)
            self._table_ensured = True
            logger.debug("[BUS] live_signals tablosu hazır (idempotent ensure)")
            return True
        except Exception as e:
            logger.warning(f"[BUS] ensure_table fail (devam, persist olmayabilir): {e}")
            return False

    # ─── PUBLIC API ────────────────────────────────────────────────────────

    def subscribe(self, signal_type: str, callback: Callable) -> None:
        """Bir sinyal tipine callback ekle.

        Callback imzası: callback(signal: dict) -> None (sync) veya async coroutine.
        signal: {type, payload, actor_phone, created_at}
        """
        if signal_type not in KNOWN_SIGNAL_TYPES:
            logger.warning(f"[BUS] Bilinmeyen sinyal tipi subscribe: {signal_type}")
        self._subscribers.setdefault(signal_type, []).append(callback)
        logger.debug(f"[BUS] subscribe: {signal_type} (toplam {len(self._subscribers[signal_type])})")

    def unsubscribe(self, signal_type: str, callback: Callable) -> bool:
        """Bir callback'i listeden çıkar. False döner = bulunamadı."""
        subs = self._subscribers.get(signal_type, [])
        try:
            subs.remove(callback)
            return True
        except ValueError:
            return False

    async def emit(
        self,
        signal_type: str,
        payload: Optional[dict] = None,
        actor_phone: str = "",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        persist: bool = True,
    ) -> dict:
        """Bir sinyal yay.

        1. In-memory subscriber'lara senkron dispatch (callback'lar çağrılır)
        2. DB'ye persist (live_signals tablosu, TTL=5dk default)

        Args:
            signal_type: pre_route, post_route, crisis_signal, ...
            payload: dict (JSONB'ye yazılır)
            actor_phone: hangi kullanıcı tetikledi
            ttl_seconds: kayıt ne kadar süre live kalsın
            persist: False ise sadece in-memory dispatch (test için)

        Returns:
            {ok, signal_id, callbacks_run, db_persisted}
        """
        if signal_type not in KNOWN_SIGNAL_TYPES:
            logger.warning(f"[BUS] Bilinmeyen sinyal emit: {signal_type}")

        signal = {
            "type": signal_type,
            "payload": payload or {},
            "actor_phone": actor_phone,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self._stats["emitted"] += 1

        # 1. In-memory dispatch
        callbacks_run = 0
        for cb in self._subscribers.get(signal_type, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(signal)
                else:
                    cb(signal)
                callbacks_run += 1
                self._stats["callbacks_run"] += 1
            except Exception as e:
                self._stats["callback_errors"] += 1
                logger.warning(f"[BUS] callback hatası ({signal_type}): {e}")

        # 2. DB persist (best-effort, hata callback'leri durdurmaz)
        signal_id = None
        if persist:
            try:
                # Tablo yoksa oluştur (idempotent, bir kere çalışır)
                if not self._table_ensured:
                    await self.ensure_table()

                from db_pool import get_pool
                pool = await get_pool()
                expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
                async with pool.acquire() as conn:
                    # Defense in depth: fermat.* prefix — search_path bagimliligi yok
                    signal_id = await conn.fetchval(
                        """INSERT INTO fermat.live_signals
                           (signal_type, payload, actor_phone, expires_at)
                           VALUES ($1, $2::jsonb, $3, $4)
                           RETURNING id""",
                        signal_type,
                        json.dumps(payload or {}, ensure_ascii=False, default=str),
                        actor_phone or None,
                        expires_at,
                    )
                self._stats["db_writes"] += 1
            except Exception as e:
                self._stats["db_errors"] += 1
                logger.debug(f"[BUS] DB persist fail ({signal_type}): {e}")

        return {
            "ok": True,
            "signal_id": signal_id,
            "callbacks_run": callbacks_run,
            "db_persisted": signal_id is not None,
        }

    async def flush_expired(self) -> int:
        """TTL geçmiş sinyalleri consumed=TRUE işaretle.

        Returns: işaretlenen kayıt sayısı.
        """
        try:
            from db_pool import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    """WITH flushed AS (
                         UPDATE fermat.live_signals
                         SET consumed = TRUE, consumed_at = NOW()
                         WHERE consumed = FALSE AND expires_at < NOW()
                         RETURNING id
                       )
                       SELECT COUNT(*) FROM flushed""",
                )
                return int(count or 0)
        except Exception as e:
            logger.debug(f"[BUS] flush_expired fail: {e}")
            return 0

    async def fetch_recent(
        self,
        signal_type: Optional[str] = None,
        actor_phone: Optional[str] = None,
        limit: int = 20,
        only_unconsumed: bool = False,
    ) -> list[dict]:
        """Son N sinyali çek (debug + audit için).

        v2 agent burayı kullanmaz (in-memory subscriber yeterli),
        ama denetim + dashboard için önemli.
        """
        try:
            from db_pool import db_fetch
            where = ["1=1"]
            params: list = [int(limit)]
            pn = 2
            if signal_type:
                where.append(f"signal_type = ${pn}")
                params.append(signal_type)
                pn += 1
            if actor_phone:
                where.append(f"actor_phone = ${pn}")
                params.append(actor_phone)
                pn += 1
            if only_unconsumed:
                where.append("consumed = FALSE")

            sql = f"""SELECT id, created_at, signal_type, payload, actor_phone, consumed
                     FROM fermat.live_signals
                     WHERE {' AND '.join(where)}
                     ORDER BY created_at DESC
                     LIMIT $1"""
            rows = await db_fetch(sql, *params)
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug(f"[BUS] fetch_recent fail: {e}")
            return []

    def get_stats(self) -> dict:
        """Bus istatistikleri (audit + sağlık)."""
        return {
            **self._stats,
            "subscriber_counts": {
                t: len(cbs) for t, cbs in self._subscribers.items()
            },
        }

    def reset_subscribers(self) -> int:
        """Tüm subscriber'ları temizle (test için)."""
        n = sum(len(cbs) for cbs in self._subscribers.values())
        self._subscribers.clear()
        return n


# Convenience module-level functions (singleton'ı dışarıdan alma kolaylaştır)
_bus: Optional[LiveSignalBus] = None


def get_bus() -> LiveSignalBus:
    """Singleton bus instance'ı döndür."""
    global _bus
    if _bus is None:
        _bus = LiveSignalBus()
    return _bus


async def emit_signal(signal_type: str, payload: dict = None,
                      actor_phone: str = "", **kw) -> dict:
    """Module-level shortcut: get_bus().emit(...)"""
    return await get_bus().emit(signal_type, payload, actor_phone, **kw)


# ─── CLI test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    async def _test():
        bus = get_bus()
        results = []

        # Test 1: subscribe + emit (in-memory, no persist)
        print("=== Test 1: in-memory subscribe + emit ===")
        called = []
        bus.subscribe("test_signal", lambda s: called.append(s["payload"]))
        await bus.emit("test_signal", {"foo": "bar"}, actor_phone="905X", persist=False)
        ok = len(called) == 1 and called[0].get("foo") == "bar"
        print(f"  callbacks_run: {len(called)}, payload: {called}")
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        # Test 2: async callback
        print()
        print("=== Test 2: async callback ===")
        async_called = []
        async def async_cb(sig):
            await asyncio.sleep(0.01)
            async_called.append(sig["payload"])
        bus.subscribe("test_signal", async_cb)
        await bus.emit("test_signal", {"async": True}, persist=False)
        ok = len(async_called) == 1 and async_called[0].get("async") is True
        print(f"  async_called: {async_called}")
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        # Test 3: DB persist
        print()
        print("=== Test 3: DB persist ===")
        r = await bus.emit("test_signal", {"persist": True}, actor_phone="905TEST", persist=True)
        print(f"  signal_id: {r.get('signal_id')}, persisted: {r.get('db_persisted')}")
        ok = r.get("db_persisted") is True and r.get("signal_id") is not None
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        # Test 4: fetch_recent
        print()
        print("=== Test 4: fetch_recent ===")
        recent = await bus.fetch_recent("test_signal", limit=3)
        print(f"  fetched: {len(recent)}")
        ok = len(recent) >= 1
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        # Test 5: stats
        print()
        print("=== Test 5: stats ===")
        stats = bus.get_stats()
        print(f"  {stats}")
        ok = stats["emitted"] >= 3 and stats["callbacks_run"] >= 3
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        # Test 6: TTL flush
        print()
        print("=== Test 6: flush_expired ===")
        # Past TTL ile bir sinyal yaz
        await bus.emit("test_signal", {"old": True}, ttl_seconds=-1, persist=True)
        await asyncio.sleep(0.1)
        flushed = await bus.flush_expired()
        print(f"  flushed: {flushed}")
        ok = flushed >= 1
        print(f"  {'PASS' if ok else 'FAIL'}")
        results.append(ok)

        print()
        passed = sum(results)
        print(f"=== {passed}/{len(results)} test PASS ===")
        return passed == len(results)

    success = asyncio.run(_test())
    sys.exit(0 if success else 1)
