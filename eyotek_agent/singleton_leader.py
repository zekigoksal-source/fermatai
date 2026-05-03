"""
FermatAI — Singleton Leader Election (25.40r — Workers=3 hazirligi)
====================================================================

Multi-worker uvicorn'da singleton background task'leri SADECE 1 worker
calistirsin. session_keeper (Eyotek CDP), scheduled tasks (gunluk rapor),
HTML updater, telafi, briefing, todo gibi cron-like loop'lar paralel
calismamali — yoksa Eyotek CDP cakisir, mesajlar 3 kez gonderilir.

KULLANIM:
    from singleton_leader import is_leader, start_leader_refresh

    async def lifespan(app):
        leader = await is_leader()
        if leader:
            asyncio.create_task(session_keeper_loop())
            asyncio.create_task(start_leader_refresh())  # TTL refresh
        # diger task'ler her worker'da calisir (idempotent)
        ...

MIMARI:
- Redis SETNX leader:bridge_singleton <worker_pid> EX 60
- Lock'u alan worker leader olur, 30sn'de bir TTL'i 60'a refresh
- Leader crash ederse 60sn icinde TTL expire — diger worker leader olur
- Memory mode (REDIS_URL bos): her zaman True — tek worker zaten singleton

NEDEN 60sn TTL:
- Crash recovery: leader olen worker'in lock'u ~60sn'de free olur
- Refresh hatasi: 30sn'de bir refresh, 1 hata olursa 30sn lock'u var
- Daha kisa TTL: cok sik refresh, network tikaniklarinda flapping
- Daha uzun TTL: crash sonrasi diger worker'lar uzun bekler
"""
from __future__ import annotations

import asyncio
import os
from loguru import logger

LEADER_KEY = "leader:bridge_singleton"
LEADER_TTL = 60       # seconds — auto-expire if worker dies
REFRESH_INTERVAL = 30  # seconds — half of TTL

_REDIS_ACTIVE = bool(os.getenv("REDIS_URL", "").strip())
_my_pid = os.getpid()
_is_leader_cache: bool | None = None  # cache result, refresh updates it


async def is_leader() -> bool:
    """Bu worker leader mi? Redis SETNX ile claim dener.

    Memory mode: her zaman True (tek worker = leader).
    Redis mode: SETNX lock alan True, alamayan False.
    Redis hata: True (fail-open — singleton task calismali).

    IDEMPOTENT: ayni worker birden fazla cagirirsa cached sonuc doner.
    """
    global _is_leader_cache
    # Idempotent — ayni worker'da tekrar cagrilirsa cache'den don
    if _is_leader_cache is not None:
        return _is_leader_cache
    if not _REDIS_ACTIVE:
        _is_leader_cache = True
        return True
    try:
        from session_store import get_store
        store = get_store()
        client = await store._get_client()
        full_key = store._k(LEADER_KEY)
        # Once mevcut leader kim diye bak — biz miyiz?
        current = await client.get(full_key)
        if current and current.decode() == str(_my_pid):
            # Zaten biz leader'iz (onceki call'dan kalmis), refresh
            await client.expire(full_key, LEADER_TTL)
            _is_leader_cache = True
            return True
        # SETNX with TTL — atomic
        ok = await client.set(full_key, str(_my_pid).encode(), nx=True, ex=LEADER_TTL)
        if ok:
            logger.info(f"  👑  Singleton leader claim: worker PID={_my_pid}")
            _is_leader_cache = True
            return True
        # Lock baska worker'da
        try:
            current = await client.get(full_key)
            current_pid = current.decode() if current else "?"
            logger.info(f"  🤝  Worker PID={_my_pid} follower (leader PID={current_pid})")
        except Exception:
            pass
        _is_leader_cache = False
        return False
    except Exception as e:
        logger.warning(f"Leader election Redis err: {e} — fail-open (singleton tasks run)")
        _is_leader_cache = True
        return True


async def start_leader_refresh():
    """Loop: 30sn'de bir TTL'i 60'a uzat. Leader degil olduysak yeni claim dene.

    Bu coroutine sonsuza kadar calisir (asyncio.create_task ile baslatilir).
    """
    global _is_leader_cache
    if not _REDIS_ACTIVE:
        return  # memory mode, refresh gerekmez
    from session_store import get_store
    while True:
        try:
            await asyncio.sleep(REFRESH_INTERVAL)
            store = get_store()
            client = await store._get_client()
            full_key = store._k(LEADER_KEY)
            current = await client.get(full_key)
            current_pid = current.decode() if current else None
            if current_pid == str(_my_pid):
                # Hala bizim, refresh
                await client.expire(full_key, LEADER_TTL)
                logger.debug(f"  👑  Leader TTL refreshed (PID={_my_pid})")
            elif current_pid is None:
                # Lock free olmus (eski leader crash) — yeni claim dene
                ok = await client.set(full_key, str(_my_pid).encode(), nx=True, ex=LEADER_TTL)
                if ok:
                    logger.warning(f"  👑  Leader takeover: PID={_my_pid} (eski leader olmus)")
                    _is_leader_cache = True
                else:
                    _is_leader_cache = False
            else:
                # Baska worker leader oldu (race condition'da nadir) — biz follower
                if _is_leader_cache:
                    logger.warning(f"  🤝  Lost leadership: yeni leader PID={current_pid}")
                    _is_leader_cache = False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"Leader refresh err: {e}")


def is_leader_cached() -> bool:
    """Cache'lenmis is_leader sonucu — async olmayan kontekstler icin.

    None ise True doner (henuz claim edilmemis = ilk run).
    """
    return _is_leader_cache if _is_leader_cache is not None else True
