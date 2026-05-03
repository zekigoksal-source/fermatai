"""
FermatAI — Hybrid State Wrappers (22.1n-neo Paket A FINAL)
============================================================

Bridge'deki _TEMP_BANS, _CLAUDE_CALLS, _PHOTO_COUNTS, _CAPACITY_COUNTS gibi
global dict'leri dict-like API ile sarmalar. Memory mode'da aynen calisir
(davranis SIFIR degisim). REDIS_URL set edilince otomatik Redis'e de yazar.

KULLANIM:
  # Eskiden:
  _TEMP_BANS: dict[str, float] = {}
  # Simdi:
  _TEMP_BANS = HybridDict("ban:", ttl_default=3600)

Bridge kodunda HIC DEGISIKLIK olmadan calisir:
  _TEMP_BANS[phone] = time.time() + 3600
  if phone in _TEMP_BANS: ...

Redis mode'da:
  - Worker A banladiginda Redis'e de yazar
  - Worker B kendi memory'sinde olmasa bile Redis'ten gorur (okuma direct)

KISITLAR:
  - Complex objeler (asyncio.Lock, class instance) serialize edilmez — memory only
  - JSON-serializable olmayan degerler sadece memory'de kalir (Redis'e yazma sessiz atlar)
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional
from loguru import logger

_REDIS_ACTIVE = bool(os.getenv("REDIS_URL", "").strip())


class HybridDict:
    """Dict-like, memory + optional Redis dual-write.

    Redis mode'da okuma SHARED (Redis öncelikli), yazma dual.
    Memory mode'da sadece memory (davranis aynen korunur).
    """

    def __init__(self, key_prefix: str, ttl_default: int = 0):
        self._mem: dict = {}
        self._prefix = key_prefix
        self._ttl_default = ttl_default

    def _rkey(self, k: str) -> str:
        return f"{self._prefix}{k}"

    # ─ Senkron dict API (eski kod hic degismez) ─

    def __setitem__(self, key, value):
        self._mem[key] = value
        if _REDIS_ACTIVE:
            # Fire-and-forget Redis write — event loop varsa create_task, yoksa skip
            try:
                loop = asyncio.get_running_loop()
                from session_store import get_store
                loop.create_task(get_store().set(
                    self._rkey(str(key)), value, ttl=self._ttl_default
                ))
            except RuntimeError:
                pass  # no running loop — sync context, memory yeterli
            except Exception:
                pass  # Redis hata olsa bile memory korundu

    def __getitem__(self, key):
        return self._mem[key]

    def __delitem__(self, key):
        self._mem.pop(key, None)
        if _REDIS_ACTIVE:
            try:
                loop = asyncio.get_running_loop()
                from session_store import get_store
                loop.create_task(get_store().delete(self._rkey(str(key))))
            except RuntimeError:
                pass
            except Exception:
                pass

    def __contains__(self, key):
        return key in self._mem

    def __len__(self):
        return len(self._mem)

    def __iter__(self):
        return iter(self._mem)

    def get(self, key, default=None):
        return self._mem.get(key, default)

    def pop(self, key, default=None):
        val = self._mem.pop(key, default)
        if _REDIS_ACTIVE:
            try:
                loop = asyncio.get_running_loop()
                from session_store import get_store
                loop.create_task(get_store().delete(self._rkey(str(key))))
            except RuntimeError:
                pass
            except Exception:
                pass
        return val

    def setdefault(self, key, default=None):
        if key not in self._mem:
            self[key] = default
        return self._mem[key]

    def items(self):
        return self._mem.items()

    def keys(self):
        return self._mem.keys()

    def values(self):
        return self._mem.values()

    async def hydrate_from_redis(self) -> int:
        """Bridge startup'ta Redis'ten memory'e yukleme.

        Persistent state across restart — bridge restart edildi ama BAN'lar
        kaybolmuyor cunku Redis'ten geri yukleniyor.

        Returns: yuklenmis key sayisi (0 = Redis yok veya anahtar yok).
        """
        if not _REDIS_ACTIVE:
            return 0
        try:
            from session_store import get_store
            store = get_store()
            pattern = f"{self._prefix}*"
            keys = await store.keys(pattern)
            loaded = 0
            for full_key in keys:
                # full_key = "ban:905..." — prefix'i cikart local key icin
                local_key = full_key[len(self._prefix):]
                val = await store.get(full_key)
                if val is not None:
                    self._mem[local_key] = val
                    loaded += 1
            if loaded > 0:
                logger.info(f"  🔄  HybridDict hydrate [{self._prefix}]: {loaded} key Redis'ten yuklendi")
            return loaded
        except Exception as e:
            logger.debug(f"hydrate err [{self._prefix}]: {e}")
            return 0

    def clear(self):
        keys = list(self._mem.keys())
        self._mem.clear()
        if _REDIS_ACTIVE:
            try:
                loop = asyncio.get_running_loop()
                from session_store import get_store
                for k in keys:
                    loop.create_task(get_store().delete(self._rkey(str(k))))
            except RuntimeError:
                pass
            except Exception:
                pass


class HybridPhoneLocks:
    """Per-phone asyncio.Lock + opsiyonel Redis distributed lock.

    Memory mode (REDIS_URL bos): sadece asyncio.Lock — tek worker'da yeterli.
    Redis mode (REDIS_URL set): asyncio.Lock (worker-ici serialize) + Redis SETNX
    (cross-worker serialize). 25.40r — Neo "workers=3 hazir olsun" direktifi.

    KULLANIM (workers >= 2 icin):
        await _PHONE_LOCKS.acquire_distributed(phone, timeout=30, ttl=180)
        try:
            async with _PHONE_LOCKS.get(phone):  # mevcut memory lock pattern
                await process_message(...)
        finally:
            await _PHONE_LOCKS.release_distributed(phone)

    Memory mode'da acquire_distributed/release_distributed no-op (her zaman True).
    Redis hatasinda degraded mode: memory lock tek basina devam eder (kullanici
    bekletilmez, sadece cross-worker serialize garantisi yok).
    """

    REDIS_LOCK_PREFIX = "plock:"

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, phone: str) -> asyncio.Lock:
        if phone not in self._locks:
            self._locks[phone] = asyncio.Lock()
        return self._locks[phone]

    def reset(self, phone: str):
        """Stale lock icin — zorla yeni lock yarat."""
        self._locks[phone] = asyncio.Lock()
        return self._locks[phone]

    def __contains__(self, phone):
        return phone in self._locks

    def __setitem__(self, phone, value):
        """Bridge stale lock recovery icin: _PHONE_LOCKS[phone] = asyncio.Lock()"""
        self._locks[phone] = value

    def __getitem__(self, phone):
        return self._locks[phone]

    def __len__(self):
        return len(self._locks)

    def keys(self):
        return self._locks.keys()

    # ─── Distributed Lock (25.40r — Workers=3 hazirligi) ───

    async def acquire_distributed(self, phone: str, timeout: float = 30.0, ttl: int = 180) -> bool:
        """Redis SETNX ile cross-worker serialize. Memory mode'da no-op (True).

        Args:
            phone: lock anahtari
            timeout: kac saniye SETNX dene (saniye)
            ttl: lock auto-expire (saniye, crash safety — worker dustugunde lock asili kalmasin)

        Returns:
            True: lock alindi (veya memory mode)
            False: SETNX timeout (baska worker hala tutuyor)
        """
        if not _REDIS_ACTIVE:
            return True
        try:
            from session_store import get_store
            store = get_store()
            client = await store._get_client()
            full_key = store._k(f"{self.REDIS_LOCK_PREFIX}{phone}")
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                # SET key val NX EX ttl — atomic SETNX with auto-expire
                ok = await client.set(full_key, b"1", nx=True, ex=ttl)
                if ok:
                    return True
                await asyncio.sleep(0.1)
            logger.warning(f"  ⏳ Distributed lock timeout {phone[-4:]} ({timeout}s)")
            return False
        except Exception as e:
            # Redis hata → degraded mode, memory lock yeter (fail-open)
            logger.warning(f"Redis distributed lock err: {e} — memory-only mode")
            return True

    async def release_distributed(self, phone: str):
        """Redis lock'u sil. Memory mode'da no-op."""
        if not _REDIS_ACTIVE:
            return
        try:
            from session_store import get_store
            store = get_store()
            client = await store._get_client()
            full_key = store._k(f"{self.REDIS_LOCK_PREFIX}{phone}")
            await client.delete(full_key)
        except Exception as e:
            logger.debug(f"Redis lock release err: {e}")

    async def is_locked_distributed(self, phone: str) -> bool:
        """Cross-worker aware locked check (memory + Redis).

        Returns True if EITHER memory or Redis lock is held.
        """
        # Memory check
        lock = self._locks.get(phone)
        if lock and lock.locked():
            return True
        # Redis check
        if not _REDIS_ACTIVE:
            return False
        try:
            from session_store import get_store
            store = get_store()
            client = await store._get_client()
            full_key = store._k(f"{self.REDIS_LOCK_PREFIX}{phone}")
            return bool(await client.exists(full_key))
        except Exception:
            return False

    def __getitem__(self, phone):
        return self.get(phone)

    def __setitem__(self, phone, lock):
        """Eski kod 'dict[phone] = asyncio.Lock()' yapiyorsa uyumlu."""
        self._locks[phone] = lock

    def pop(self, phone, default=None):
        return self._locks.pop(phone, default)


def is_redis_mode() -> bool:
    return _REDIS_ACTIVE


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        print(f"Redis mode: {_REDIS_ACTIVE}")
        d = HybridDict("test:", ttl_default=5)
        d["905000"] = time.time() + 100
        print(f"Set OK: 905000 in d = {'905000' in d}")
        print(f"Value: {d['905000']}")
        d.pop("905000", None)
        print(f"After pop: 905000 in d = {'905000' in d}")

        locks = HybridPhoneLocks()
        L = locks.get("905001")
        async with L:
            print("Lock acquired OK")

    asyncio.run(main())
