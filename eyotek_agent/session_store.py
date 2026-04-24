"""
FermatAI — Session Store (22.1n-neo Paket A FINAL)
====================================================

Multi-worker icin per-phone state merkezi. Default: MEMORY (tek worker).
REDIS_URL env set edilirse Redis'e baglar — worker'lar arasi paylasim.

KULLANIM:
  from session_store import get_store, acquire_lock, add_to_window, get_window_count
  store = get_store()
  await store.set("ban:905...", True, ttl=3600)

OPERASYONLAR:
  - get/set/delete/exists/ttl           (basit KV)
  - list_push/list_range/list_trim      (kuyruk - PHONE_QUEUES)
  - zset_add/zset_count_in_range        (zamanli sayac - CAPACITY, CLAUDE_CALLS)
  - hash_set/hash_get                   (phone bazli sozluk - PHOTO_COUNTS)
  - acquire_lock/release_lock           (distributed - PHONE_LOCKS)

MOD SECIMI:
  REDIS_URL bos    → MemoryStore (local, davranis AYNI)
  REDIS_URL set    → RedisStore (distributed)

NOTLAR:
  - Memory mode → tum bridge kodundaki mevcut davranis SIFIR degisim
  - Redis mode → multi-worker + restart-safe
  - pickle/json: str ve dict degerler otomatik serialize
  - TTL: otomatik expire (ban 1h, agent 1d, lock 5dk)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional, Any, List
from loguru import logger


REDIS_URL = os.getenv("REDIS_URL", "").strip()


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY STORE — default, single worker
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryStore:
    """In-process. Davranis degismez, bridge kodu direkt memory dict kullaniyor
    gibi calisir ama store interface'i sayesinde Redis'e swap edilebilir."""

    def __init__(self):
        self._kv: dict = {}           # string/dict values
        self._ttl: dict = {}          # expiry timestamps
        self._lists: dict = {}        # queue-like
        self._zsets: dict = {}        # {key: [(member, score), ...]}
        self._hashes: dict = {}       # {key: {field: value}}
        self._locks: dict = {}        # {key: asyncio.Lock}

    # ─ TTL yardımcı ─
    def _expired(self, key: str) -> bool:
        exp = self._ttl.get(key)
        if exp and time.time() > exp:
            self._kv.pop(key, None)
            self._ttl.pop(key, None)
            self._lists.pop(key, None)
            self._zsets.pop(key, None)
            self._hashes.pop(key, None)
            return True
        return False

    # ─ Basit KV ─
    async def get(self, key: str) -> Optional[Any]:
        if self._expired(key): return None
        return self._kv.get(key)

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        self._kv[key] = value
        if ttl > 0:
            self._ttl[key] = time.time() + ttl
        elif key in self._ttl:
            self._ttl.pop(key, None)

    async def delete(self, key: str) -> None:
        self._kv.pop(key, None)
        self._ttl.pop(key, None)
        self._lists.pop(key, None)
        self._zsets.pop(key, None)
        self._hashes.pop(key, None)

    async def exists(self, key: str) -> bool:
        if self._expired(key): return False
        return key in self._kv or key in self._lists or key in self._zsets or key in self._hashes

    async def ttl(self, key: str) -> int:
        exp = self._ttl.get(key)
        if not exp: return -1
        remain = int(exp - time.time())
        return max(0, remain)

    # ─ List (kuyruk) ─
    async def list_push(self, key: str, value: Any) -> int:
        lst = self._lists.setdefault(key, [])
        lst.append(value)
        return len(lst)

    async def list_pop_left(self, key: str) -> Optional[Any]:
        lst = self._lists.get(key)
        if not lst: return None
        return lst.pop(0)

    async def list_range(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        lst = self._lists.get(key) or []
        if end == -1: return lst[start:]
        return lst[start:end+1]

    async def list_len(self, key: str) -> int:
        return len(self._lists.get(key) or [])

    # ─ Sorted set (zamanli sayac) ─
    async def zset_add(self, key: str, score: float, member: Any) -> int:
        zs = self._zsets.setdefault(key, [])
        zs.append((member, score))
        return 1

    async def zset_remove_by_score(self, key: str, min_score: float, max_score: float) -> int:
        zs = self._zsets.get(key)
        if not zs: return 0
        before = len(zs)
        zs[:] = [(m, s) for m, s in zs if not (min_score <= s <= max_score)]
        return before - len(zs)

    async def zset_count_in_range(self, key: str, min_score: float, max_score: float) -> int:
        zs = self._zsets.get(key) or []
        return sum(1 for _, s in zs if min_score <= s <= max_score)

    async def zset_trim_old(self, key: str, cutoff_score: float) -> int:
        """cutoff_score'tan eski uyelerle kaldir (ban/cap temizlik)."""
        zs = self._zsets.get(key)
        if not zs: return 0
        before = len(zs)
        zs[:] = [(m, s) for m, s in zs if s >= cutoff_score]
        return before - len(zs)

    # ─ Hash (nested dict) ─
    async def hash_set(self, key: str, field: str, value: Any) -> None:
        self._hashes.setdefault(key, {})[field] = value

    async def hash_get(self, key: str, field: str) -> Optional[Any]:
        return self._hashes.get(key, {}).get(field)

    async def hash_del_field(self, key: str, field: str) -> None:
        if key in self._hashes:
            self._hashes[key].pop(field, None)

    async def hash_all(self, key: str) -> dict:
        return dict(self._hashes.get(key, {}))

    # ─ Lock (asyncio — memory için normal asyncio.Lock) ─
    def sync_lock(self, key: str) -> asyncio.Lock:
        """asyncio.Lock dondur (her key icin tekil)."""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def keys(self, pattern: str) -> list:
        """Pattern'e uyan key listesi. Pattern 'ban:*' gibi prefix."""
        import fnmatch
        return [k for k in list(self._kv.keys()) if fnmatch.fnmatch(k, pattern)]

    async def close(self):
        self._kv.clear()
        self._ttl.clear()
        self._lists.clear()
        self._zsets.clear()
        self._hashes.clear()
        self._locks.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS STORE — multi-worker
# ═══════════════════════════════════════════════════════════════════════════════

class RedisStore:
    """Production. redis.asyncio ile distributed state."""

    PREFIX = "fermat:"

    def __init__(self, url: str):
        self.url = url
        self._client = None

    async def _get_client(self):
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(
                self.url, decode_responses=False,
                max_connections=20, socket_timeout=5,
            )
            await self._client.ping()
            logger.info(f"  🔴  Redis baglandi: {self.url}")
        return self._client

    def _k(self, key: str) -> str:
        return self.PREFIX + key

    # ─ KV ─
    async def get(self, key: str) -> Optional[Any]:
        try:
            raw = await (await self._get_client()).get(self._k(key))
            if raw is None: return None
            try: return json.loads(raw)
            except: return raw.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"redis get err: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 0) -> None:
        try:
            raw = json.dumps(value, ensure_ascii=False, default=str)
            c = await self._get_client()
            if ttl > 0:
                await c.setex(self._k(key), ttl, raw)
            else:
                await c.set(self._k(key), raw)
        except Exception as e:
            logger.debug(f"redis set err: {e}")

    async def delete(self, key: str) -> None:
        try:
            await (await self._get_client()).delete(self._k(key))
        except Exception: pass

    async def exists(self, key: str) -> bool:
        try:
            return bool(await (await self._get_client()).exists(self._k(key)))
        except Exception: return False

    async def ttl(self, key: str) -> int:
        try:
            return await (await self._get_client()).ttl(self._k(key))
        except Exception: return -1

    # ─ List ─
    async def list_push(self, key: str, value: Any) -> int:
        try:
            raw = json.dumps(value, ensure_ascii=False, default=str)
            return await (await self._get_client()).rpush(self._k(key), raw)
        except Exception: return 0

    async def list_pop_left(self, key: str) -> Optional[Any]:
        try:
            raw = await (await self._get_client()).lpop(self._k(key))
            if raw is None: return None
            try: return json.loads(raw)
            except: return raw.decode("utf-8", errors="replace")
        except Exception: return None

    async def list_range(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        try:
            raw_list = await (await self._get_client()).lrange(self._k(key), start, end)
            out = []
            for raw in raw_list:
                try: out.append(json.loads(raw))
                except: out.append(raw.decode("utf-8", errors="replace"))
            return out
        except Exception: return []

    async def list_len(self, key: str) -> int:
        try:
            return await (await self._get_client()).llen(self._k(key))
        except Exception: return 0

    # ─ Sorted set ─
    async def zset_add(self, key: str, score: float, member: Any) -> int:
        try:
            m = json.dumps(member, ensure_ascii=False, default=str) if not isinstance(member, (str, bytes)) else str(member)
            return await (await self._get_client()).zadd(self._k(key), {m: float(score)})
        except Exception: return 0

    async def zset_count_in_range(self, key: str, min_score: float, max_score: float) -> int:
        try:
            return await (await self._get_client()).zcount(self._k(key), float(min_score), float(max_score))
        except Exception: return 0

    async def zset_trim_old(self, key: str, cutoff_score: float) -> int:
        try:
            return await (await self._get_client()).zremrangebyscore(self._k(key), '-inf', float(cutoff_score))
        except Exception: return 0

    # ─ Hash ─
    async def hash_set(self, key: str, field: str, value: Any) -> None:
        try:
            raw = json.dumps(value, ensure_ascii=False, default=str)
            await (await self._get_client()).hset(self._k(key), field, raw)
        except Exception: pass

    async def hash_get(self, key: str, field: str) -> Optional[Any]:
        try:
            raw = await (await self._get_client()).hget(self._k(key), field)
            if raw is None: return None
            try: return json.loads(raw)
            except: return raw.decode("utf-8", errors="replace")
        except Exception: return None

    async def hash_del_field(self, key: str, field: str) -> None:
        try:
            await (await self._get_client()).hdel(self._k(key), field)
        except Exception: pass

    async def hash_all(self, key: str) -> dict:
        try:
            raw = await (await self._get_client()).hgetall(self._k(key))
            return {f.decode(): json.loads(v) for f, v in raw.items()}
        except Exception: return {}

    async def keys(self, pattern: str) -> list:
        """fermat:{pattern} prefix'ine uyan anahtarlari don (PREFIX'siz)."""
        try:
            c = await self._get_client()
            raw = await c.keys(self.PREFIX + pattern)
            # prefix'i kaldir
            return [k.decode()[len(self.PREFIX):] for k in raw]
        except Exception as e:
            logger.debug(f"redis keys err: {e}")
            return []

    async def close(self):
        if self._client:
            try: await self._client.aclose()
            except: pass


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY + UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

_STORE: Optional[Any] = None


def get_store():
    """Adapter secimi — REDIS_URL varsa Redis, yoksa Memory."""
    global _STORE
    if _STORE is None:
        if REDIS_URL:
            _STORE = RedisStore(REDIS_URL)
            logger.info(f"  Session store: REDIS ({REDIS_URL})")
        else:
            _STORE = MemoryStore()
            logger.debug("  Session store: MEMORY (single worker default)")
    return _STORE


# ─── Yardımcı fonksiyonlar (bridge'den kolay kullanim) ────────────────────────

async def add_timestamped(key: str, score: float = None, window_sec: int = 300) -> int:
    """Zamanli event ekle + penceren disi eski olanlari temizle.

    Kullanim: rate limit — add_timestamped('cap:905...', window_sec=300) → 5dk pencere
    Returns: pencereler icindeki toplam event sayisi (eklenen dahil)
    """
    if score is None:
        score = time.time()
    store = get_store()
    await store.zset_add(key, score, f"{score}")
    cutoff = score - window_sec
    await store.zset_trim_old(key, cutoff)
    return await store.zset_count_in_range(key, cutoff, score + 1)


async def count_in_window(key: str, window_sec: int = 300) -> int:
    """Pencere icindeki event sayisi — eklemeden, sadece sayma."""
    now = time.time()
    return await get_store().zset_count_in_range(key, now - window_sec, now + 1)


# Ban helpers
async def set_ban(phone: str, duration_sec: int = 3600):
    await get_store().set(f"ban:{phone}", True, ttl=duration_sec)


async def is_banned(phone: str) -> bool:
    return await get_store().exists(f"ban:{phone}")


async def clear_ban(phone: str):
    await get_store().delete(f"ban:{phone}")


# Daily counter helpers
async def daily_counter_inc(phone: str, name: str, today: str) -> int:
    """Gunluk sayac + 1. Returns: yeni sayi."""
    store = get_store()
    key = f"daily:{phone}:{name}"
    cur = await store.hash_get(key, today)
    new = (int(cur) if cur else 0) + 1
    await store.hash_set(key, today, new)
    # TTL: 48 saat (eski gün otomatik dusmez ama key alaninda kalir — temizlik opsiyonel)
    return new


async def daily_counter_get(phone: str, name: str, today: str) -> int:
    cur = await get_store().hash_get(f"daily:{phone}:{name}", today)
    return int(cur) if cur else 0


async def health_check() -> dict:
    store = get_store()
    store_type = type(store).__name__
    ok = True
    try:
        await store.set("health:probe", "ok", ttl=10)
        v = await store.get("health:probe")
        ok = (v == "ok")
    except Exception:
        ok = False
    return {"type": store_type, "ok": ok, "redis_url_set": bool(REDIS_URL)}


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    async def main():
        print(f"REDIS_URL: {REDIS_URL or '(not set — MEMORY mode)'}")
        h = await health_check()
        print(f"Store: {h['type']}, OK: {h['ok']}")

        s = get_store()
        # KV
        await s.set("t:1", {"a": 1}, ttl=5)
        print("KV:", await s.get("t:1"))
        # List
        await s.list_push("q:1", "msg1")
        await s.list_push("q:1", "msg2")
        print("List len:", await s.list_len("q:1"))
        print("List:", await s.list_range("q:1"))
        # Zset (rate limit)
        n1 = await add_timestamped("cap:test", window_sec=60)
        n2 = await add_timestamped("cap:test", window_sec=60)
        n3 = await add_timestamped("cap:test", window_sec=60)
        print(f"Zset count (3 ekledik): {n3}")
        # Hash
        await s.hash_set("photo:test", "2026-04-21", 2)
        print("Hash get:", await s.hash_get("photo:test", "2026-04-21"))
        # Ban
        await set_ban("905000", 5)
        print("Banned:", await is_banned("905000"))
        await clear_ban("905000")
        print("After clear:", await is_banned("905000"))
        # Daily
        n = await daily_counter_inc("905000", "foto", "2026-04-21")
        print(f"Daily counter: {n}")

    asyncio.run(main())
