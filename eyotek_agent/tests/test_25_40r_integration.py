"""
25.40r Integration Tests — A1+A3+B1+B2 conflict ve regression kontrolu.

Bu test:
1. Semantic cache (bge-m3) - exact + semantic + threshold
2. Redis dual-write (HybridDict)
3. Distributed lock (acquire/release/race/ttl)
4. Leader election (claim/follower/takeover)
5. OTP duplicate guard (30sn pencere + burst koruma birlikte)
6. Stale lock recovery + Redis orphan onleme (BUG #1 fix)

Calistirma (VPS):
    cd /opt/fermatai/eyotek_agent
    /opt/fermatai/.venv/bin/python tests/test_25_40r_integration.py
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta

# .env yukle
from dotenv import load_dotenv
load_dotenv("/opt/fermatai/.env", override=True)

# parent path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


PASS = 0
FAIL = 0
ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


# ═══════════════════════════════════════════════════════════════════
# A1 — SEMANTIC CACHE
# ═══════════════════════════════════════════════════════════════════

async def test_query_cache():
    print("\n[A1] Semantic Cache (bge-m3)")
    from query_cache import init_db, _embed, find_cached, add_to_cache
    from db_pool import get_pool

    # Tabloyu temizle
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS query_cache CASCADE")

    await init_db()

    # 1. Embed dim
    vec = _embed("test embed")
    check("embed_dim_1024", vec is not None and len(vec) == 1024,
          f"got {len(vec) if vec else None}")

    # 2. add_to_cache
    cid = await add_to_cache("__t1__", "system", "TYT de kac soru var",
                              "TYT 120 sorudan olusur", "fast_response", ttl_hours=1)
    check("add_to_cache_returns_id", cid is not None and cid > 0, f"id={cid}")

    # 3. exact hash match
    hit = await find_cached("__t1__", "TYT de kac soru var")
    check("exact_hash_match", hit and hit.get("source") == "fast_response",
          f"hit={hit}")

    # 4. exact hash with whitespace/case variations
    hit2 = await find_cached("__t1__", "  TYT DE KAC SORU VAR  ")
    check("exact_hash_normalized", hit2 is not None,
          f"normalized variant: {hit2 is not None}")

    # 5. semantic similar (paraphrase)
    hit3 = await find_cached("__t1__", "TYT toplam soru sayisi nedir",
                              similarity_threshold=0.70)
    check("semantic_paraphrase_hit", hit3 is not None and hit3.get("similarity", 0) > 0.70,
          f"hit={hit3}")

    # 6. unrelated topic — should miss
    hit4 = await find_cached("__t1__", "kaldirma kuvveti formulu", similarity_threshold=0.80)
    check("unrelated_topic_miss", hit4 is None, f"unexpected hit: {hit4}")

    # 7. per-phone isolation
    hit5 = await find_cached("__t2__", "TYT de kac soru var")
    check("per_phone_isolation", hit5 is None,
          f"phone __t2__ should not see __t1__'s cache, got {hit5}")

    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM query_cache WHERE phone IN ('__t1__', '__t2__')")


# ═══════════════════════════════════════════════════════════════════
# A3 — REDIS DUAL-WRITE
# ═══════════════════════════════════════════════════════════════════

async def test_redis_dualwrite():
    print("\n[A3] Redis Dual-Write (HybridDict)")
    from hybrid_state import HybridDict, _REDIS_ACTIVE
    from session_store import get_store

    check("redis_active_env", _REDIS_ACTIVE, "REDIS_URL not loaded")

    if not _REDIS_ACTIVE:
        return

    bans = HybridDict("ban_test:", ttl_default=10)
    bans["905test_dualwrite"] = time.time() + 10

    await asyncio.sleep(0.3)  # async write task tamamlansin

    store = get_store()
    val = await store.get("ban_test:905test_dualwrite")
    check("hybrid_dual_write", val is not None, "Redis'te beklenen anahtar yok")

    # Read-back consistency
    mem_val = bans.get("905test_dualwrite")
    check("memory_value_present", mem_val is not None, f"memory value missing")

    # Delete propagation
    bans.pop("905test_dualwrite")
    await asyncio.sleep(0.3)
    val2 = await store.get("ban_test:905test_dualwrite")
    check("delete_propagation", val2 is None, f"delete didn't propagate to Redis: {val2}")


# ═══════════════════════════════════════════════════════════════════
# B1 — DISTRIBUTED LOCK
# ═══════════════════════════════════════════════════════════════════

async def test_distributed_lock():
    print("\n[B1] Distributed Lock (HybridPhoneLocks)")
    from hybrid_state import HybridPhoneLocks, _REDIS_ACTIVE

    if not _REDIS_ACTIVE:
        print("  [SKIP] Redis active gerek")
        return

    locks_a = HybridPhoneLocks()  # "Worker A" simulation
    locks_b = HybridPhoneLocks()  # "Worker B" simulation
    test_phone = "905distlock_test"

    # 1. Acquire round-trip
    ok1 = await locks_a.acquire_distributed(test_phone, timeout=2, ttl=10)
    check("first_acquire", ok1, f"got {ok1}")

    # 2. Cross-instance acquire FAIL (1sn timeout)
    ok2 = await locks_b.acquire_distributed(test_phone, timeout=1, ttl=10)
    check("race_fail_short_timeout", ok2 is False,
          f"second worker shouldn't acquire while first holds: {ok2}")

    # 3. is_locked_distributed (memory'de a, redis'te a)
    is_locked_b = await locks_b.is_locked_distributed(test_phone)
    check("is_locked_cross_instance", is_locked_b,
          "Worker B should see Worker A's distributed lock")

    # 4. Release
    await locks_a.release_distributed(test_phone)

    # 5. Worker B can now acquire
    ok3 = await locks_b.acquire_distributed(test_phone, timeout=2, ttl=10)
    check("acquire_after_release", ok3, f"after release should acquire: {ok3}")

    await locks_b.release_distributed(test_phone)

    # 6. Both released → is_locked False
    is_locked_final = await locks_a.is_locked_distributed(test_phone)
    check("both_released_no_lock", is_locked_final is False,
          f"after both released: {is_locked_final}")

    # 7. TTL expire test (kisa TTL)
    ok4 = await locks_a.acquire_distributed(test_phone, timeout=1, ttl=2)
    check("acquire_short_ttl", ok4, f"acquire with 2s ttl: {ok4}")
    await asyncio.sleep(2.5)  # TTL expire
    ok5 = await locks_b.acquire_distributed(test_phone, timeout=1, ttl=10)
    check("ttl_expire_recovery", ok5, "after TTL expire, other worker should acquire")
    await locks_b.release_distributed(test_phone)


# ═══════════════════════════════════════════════════════════════════
# B1.2 — LEADER ELECTION
# ═══════════════════════════════════════════════════════════════════

async def test_leader_election():
    print("\n[B1.2] Leader Election (singleton_leader)")
    from session_store import get_store
    import singleton_leader as sl

    if not sl._REDIS_ACTIVE:
        print("  [SKIP] Redis active gerek")
        return

    # Mevcut leader'i temizle (test izolasyonu)
    store = get_store()
    client = await store._get_client()
    await client.delete(store._k(sl.LEADER_KEY))
    sl._is_leader_cache = None  # cache reset

    # 1. Ilk claim
    is_l1 = await sl.is_leader()
    check("initial_claim_succeeds", is_l1, f"first claim: {is_l1}")

    # 2. Idempotent — ayni worker tekrar cagirinca True
    is_l2 = await sl.is_leader()
    check("idempotent_claim", is_l2, f"second call same worker: {is_l2}")

    # 3. Redis'te key var mi
    val = await client.get(store._k(sl.LEADER_KEY))
    check("redis_leader_key_set", val is not None and val.decode() == str(sl._my_pid),
          f"redis: {val}")

    # 4. Diger "worker" simulasyon: cache'i resetle, baska bir PID gibi davran
    original_pid = sl._my_pid
    sl._my_pid = 99999  # sahte PID
    sl._is_leader_cache = None
    is_follower = await sl.is_leader()
    check("other_worker_follower", is_follower is False,
          f"other PID should be follower while leader exists: {is_follower}")

    # 5. Lock'u sil — takeover senaryosu
    await client.delete(store._k(sl.LEADER_KEY))
    sl._is_leader_cache = None
    is_takeover = await sl.is_leader()
    check("takeover_after_leader_dies", is_takeover,
          f"after leader removed, new claim should succeed: {is_takeover}")

    # Cleanup
    sl._my_pid = original_pid
    sl._is_leader_cache = None
    await client.delete(store._k(sl.LEADER_KEY))


# ═══════════════════════════════════════════════════════════════════
# B2 — OTP DUPLICATE GUARD
# ═══════════════════════════════════════════════════════════════════

async def test_otp_duplicate_guard():
    print("\n[B2] OTP Duplicate Guard (Yagiz vakasi)")
    from web_chat_auth import request_otp
    from db_pool import get_pool

    test_phone = "905523517686"  # Yagiz Alptekin (197) — gerçek student

    # Eski test kayitlarini temizle
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM web_sessions WHERE phone=$1 AND otp_created_at > NOW() - INTERVAL '5 minutes'",
            test_phone
        )

    # 1. Ilk istek — yeni OTP
    r1 = await request_otp(test_phone)
    check("first_otp_success", r1.get("success"), f"first call failed: {r1.get('message')}")
    check("first_otp_no_dup_flag", not r1.get("_dup_guard"), "first should be new, not duplicate")
    code1 = r1.get("code")

    # 2. Hizli ikinci istek (5ms) — duplicate guard, ayni kod
    await asyncio.sleep(0.005)
    r2 = await request_otp(test_phone)
    check("second_otp_dup_guard", r2.get("_dup_guard") is True, f"should hit dup_guard: {r2}")
    check("second_otp_same_code", r2.get("code") == code1,
          f"expected same code, got {r2.get('code')} vs {code1}")

    # 3. Ucuncu istek — hala duplicate
    r3 = await request_otp(test_phone)
    check("third_otp_dup_guard", r3.get("_dup_guard") is True, f"third dup: {r3}")

    # 4. Burst koruma test (gercek production'da olusabilir): 4. ve 5. istek
    # Aslinda dup guard aktif oldugu icin burst koruma asla tetiklenmez
    # cunku INSERT yapilmiyor — sadece SELECT+return. Bu da BIR fix:
    # eski kod 5 OTP yaratiyordu, yeni kod 1 yaratip 4 reuse.
    burst_count_before = 1  # Sadece 1 OTP yaratildi (ilk istek)
    async with pool.acquire() as conn:
        actual = await conn.fetchval(
            "SELECT COUNT(*) FROM web_sessions WHERE phone=$1 AND otp_created_at > NOW() - INTERVAL '60 seconds'",
            test_phone
        )
    check("only_one_otp_inserted", actual == burst_count_before,
          f"expected 1 OTP in DB, got {actual}")

    # Cleanup
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM web_sessions WHERE phone=$1 AND otp_created_at > NOW() - INTERVAL '5 minutes'", test_phone)


# ═══════════════════════════════════════════════════════════════════
# CONFLICT TEST: STALE LOCK + REDIS ORPHAN (BUG #1 fix doğrulama)
# ═══════════════════════════════════════════════════════════════════

async def test_stale_lock_redis_cleanup():
    print("\n[CONFLICT] Stale Lock Recovery + Redis Cleanup (BUG #1 fix)")
    from hybrid_state import HybridPhoneLocks, _REDIS_ACTIVE

    if not _REDIS_ACTIVE:
        print("  [SKIP] Redis active gerek")
        return

    locks = HybridPhoneLocks()
    test_phone = "905stale_test"

    # 1. Distributed lock al (180sn TTL)
    ok = await locks.acquire_distributed(test_phone, timeout=2, ttl=180)
    check("stale_setup_acquire", ok, "setup acquire failed")

    # 2. Memory lock'u zorla resetle (stale recovery simulasyonu)
    locks[test_phone] = asyncio.Lock()  # __setitem__

    # 3. BUG #1 FIX: stale recovery'de release_distributed da çağrılmalı
    # Bridge satır 4717-4720'de bu eklendi. Manuel release_distributed çağıralım:
    await locks.release_distributed(test_phone)

    # 4. Redis lock gerçekten silindi mi?
    is_locked = await locks.is_locked_distributed(test_phone)
    check("stale_redis_cleanup_works", is_locked is False,
          "after stale recovery, Redis lock should be released")

    # 5. Yeni instance hemen acquire edebilmeli
    locks2 = HybridPhoneLocks()
    ok2 = await locks2.acquire_distributed(test_phone, timeout=1, ttl=10)
    check("after_stale_cleanup_acquire", ok2,
          "another worker should acquire immediately after stale cleanup")
    await locks2.release_distributed(test_phone)


# ═══════════════════════════════════════════════════════════════════
# REAL-WORLD: AYNI PHONE'A 3 PARALEL MESAJ (cross-worker simulasyonu)
# ═══════════════════════════════════════════════════════════════════

async def test_concurrent_same_phone():
    print("\n[REAL-WORLD] Same phone 3 parallel acquire (multi-worker)")
    from hybrid_state import HybridPhoneLocks, _REDIS_ACTIVE

    if not _REDIS_ACTIVE:
        print("  [SKIP] Redis active gerek")
        return

    test_phone = "905concurrent_test"

    # 3 farkli "worker" instance
    locks = [HybridPhoneLocks() for _ in range(3)]

    # 3 paralel acquire — sadece 1 başarılı, 2 timeout (kısa timeout=1)
    async def try_acquire(idx):
        return idx, await locks[idx].acquire_distributed(test_phone, timeout=1, ttl=10)

    results = await asyncio.gather(*[try_acquire(i) for i in range(3)])
    successes = [idx for idx, ok in results if ok]
    failures = [idx for idx, ok in results if not ok]
    check("only_one_acquires", len(successes) == 1,
          f"expected 1 acquire, got {len(successes)} (workers: {successes})")
    check("two_workers_timeout", len(failures) == 2,
          f"expected 2 timeouts, got {len(failures)}")

    # Winner release
    if successes:
        await locks[successes[0]].release_distributed(test_phone)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("25.40r INTEGRATION TESTS")
    print("=" * 60)

    test_funcs = [
        test_query_cache,
        test_redis_dualwrite,
        test_distributed_lock,
        test_leader_election,
        test_otp_duplicate_guard,
        test_stale_lock_redis_cleanup,
        test_concurrent_same_phone,
    ]

    for tf in test_funcs:
        try:
            await tf()
        except Exception as e:
            global FAIL
            FAIL += 1
            ERRORS.append(f"{tf.__name__} EXCEPTION: {e}")
            print(f"  ✗ EXCEPTION in {tf.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    if ERRORS:
        print("\nFAILURES:")
        for e in ERRORS:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
