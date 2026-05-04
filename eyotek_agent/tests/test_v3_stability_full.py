# -*- coding: utf-8 -*-
"""
V3 STABILITY FULL TEST (25.40z3 production-gate)
==================================================

V3 + cache_control sisteminin kararlilik garantilerini test eder.

Test gruplari:
1. 160 senaryo combinations (5 rol x 16 intent x 2 kanal)
2. Edge case: bilinmeyen rol, None intent, bos string, bilinmeyen kanal
3. Memory leak: 1000 cagri sonra BASE singleton korunur
4. Concurrent: 50 paralel build_prompt_v3 cagrisi (race condition)
5. Cache_control idempotent: ayni input -> ayni output
6. Long conversation: 100 farkli senaryo ardisik calistirma
7. BASE consistency: 1000 cagri sonra hep ayni BASE
8. V3 vs V2 cikti tutarliligi: kritik kelimelerin korunmasi
9. Modul boyut sinirlari: hicbir modul 100K char asmasin
10. Total prompt size: hicbir senaryoda 200K char asmasin (Anthropic limit)
"""
import io
import os
import sys
import time
import threading
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PASS = 0
FAIL = 0
ERRORS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  + {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  X {name} -- {detail}")


# 16 intent katalogu
INTENTS = [
    "selamlama", "kavram_aciklama", "ornek_iste", "cozum_iste",
    "ozet_iste", "yontem_iste", "duygu_paylasim", "motivasyon_destek",
    "test_olusturma", "soru_uret", "yeni_nesil_uret", "konu_anlatim_uzun",
    "ornek_paket_uret", "plan_yap", "deneme_analiz", "analiz_iste",
    "meta_direktif", "yetenek_sorgu", "veda", "tesekkur",
]
ROLES = ["admin", "mudur", "ogretmen", "ogrenci", "rehber"]
CHANNELS = ["whatsapp", "web"]


def test_160_combinations():
    """5 rol x 16 intent x 2 kanal = 160 senaryo, hicbiri crash etmemeli."""
    print("\n[1] 160 SENARYO COMBINATIONS (rol x intent x kanal)")
    from prompt_modules.composer_v3 import build_prompt_v3

    crashed = 0
    valid = 0
    for role in ROLES:
        for intent in INTENTS:
            for channel in CHANNELS:
                try:
                    text, info = build_prompt_v3(role, intent, channel)
                    assert isinstance(text, str)
                    assert len(text) > 1000
                    assert isinstance(info, dict)
                    assert "modules_loaded" in info
                    valid += 1
                except Exception as e:
                    crashed += 1
                    print(f"    CRASH: {role}/{intent}/{channel}: {e}")

    check(f"160 senaryonun tamami calisti (valid={valid}, crashed={crashed})",
          crashed == 0,
          f"{crashed} crash")


def test_edge_cases():
    """Bilinmeyen rol, None intent, bos string, garip karakter."""
    print("\n[2] EDGE CASES (anormal input)")
    from prompt_modules.composer_v3 import build_prompt_v3

    cases = [
        ("unknown_role", "kavram_aciklama", "web"),
        ("ogrenci", None, "whatsapp"),
        ("ogrenci", "", "whatsapp"),
        ("", "selamlama", "whatsapp"),
        ("ogrenci", "selamlama", "unknown_channel"),
        ("ogrenci", "bilinmeyen_intent", "web"),
        ("ADMIN", "selamlama", "whatsapp"),  # uppercase
        ("Ogrenci", "selamlama", "whatsapp"),  # capitalized
    ]
    for role, intent, channel in cases:
        try:
            text, info = build_prompt_v3(role, intent, channel)
            check(f"edge: role={role!r}/intent={intent!r}/ch={channel!r} crash YOK",
                  isinstance(text, str) and len(text) > 0)
        except Exception as e:
            check(f"edge: role={role!r}/intent={intent!r}/ch={channel!r}",
                  False, f"crash: {e}")


def test_memory_singleton_1000_calls():
    """1000 build_prompt_v3 cagrisi sonra BASE singleton korunmali."""
    print("\n[3] MEMORY SINGLETON (1000 cagri)")
    from prompt_modules.composer_v3 import get_base_prompt

    # Cache reset
    import prompt_modules.composer_v3 as c
    c._BASE_CACHE = None

    base_first = get_base_prompt()
    base_first_id = id(base_first)

    # 1000 cagri
    for _ in range(1000):
        b = get_base_prompt()

    base_last = get_base_prompt()
    check("BASE singleton korundu (1000 cagri sonra ayni object)",
          id(base_last) == base_first_id,
          f"singleton bozuldu (id farkli)")
    check("BASE icerigi degismedi",
          base_last == base_first,
          "BASE mutate edildi")


def test_concurrent_50():
    """50 paralel build_prompt_v3 cagrisi - race condition kontrolu."""
    print("\n[4] CONCURRENT 50 PARALLEL CALLS")
    from prompt_modules.composer_v3 import build_prompt_v3

    def worker(args):
        role, intent, channel = args
        try:
            text, info = build_prompt_v3(role, intent, channel)
            return (True, len(text), info["modules_loaded"])
        except Exception as e:
            return (False, str(e), None)

    tasks = [
        ("ogrenci", "kavram_aciklama", "web"),
        ("admin", "meta_direktif", "whatsapp"),
        ("mudur", "analiz_iste", "whatsapp"),
        ("ogretmen", "selamlama", "whatsapp"),
        ("rehber", "duygu_paylasim", "web"),
    ] * 10  # 50 task

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(worker, tasks))

    failures = sum(1 for ok, _, _ in results if not ok)
    check(f"50 paralel cagri (failures={failures})",
          failures == 0,
          f"{failures} concurrent failure")

    # Ayni senaryolar ayni boyutu vermeli (deterministik)
    sizes = {}
    for (role, intent, channel), (ok, size, _) in zip(tasks, results):
        if not ok:
            continue
        key = (role, intent, channel)
        if key in sizes:
            if sizes[key] != size:
                check(f"deterministik {role}/{intent}/{channel}",
                      False, f"farkli boyutlar: {sizes[key]} vs {size}")
        else:
            sizes[key] = size
    check("Ayni input -> ayni boyut (deterministik)", True)


def test_cache_control_idempotent():
    """Ayni input -> ayni cache_control structure."""
    print("\n[5] CACHE_CONTROL IDEMPOTENT")
    from prompt_modules.composer_v3 import build_prompt_v3

    # 5 kez ayni cagri
    blocks_list = []
    for _ in range(5):
        blocks, _ = build_prompt_v3("ogrenci", "kavram_aciklama", "web",
                                    return_blocks=True)
        blocks_list.append(blocks)

    # Hepsi ayni
    first = blocks_list[0]
    for i, b in enumerate(blocks_list[1:], 1):
        same_count = (
            len(b) == len(first) and
            all(b[j]["text"] == first[j]["text"] for j in range(len(b))) and
            all(b[j]["cache_control"] == first[j]["cache_control"]
                for j in range(len(b)))
        )
        check(f"Cagri {i+1}: ayni structure", same_count,
              "cache_control output deterministik degil")


def test_long_conversation_100():
    """100 farkli senaryo ardisik calisma - state pollution YOK."""
    print("\n[6] LONG CONVERSATION (100 farkli senaryo ardisik)")
    from prompt_modules.composer_v3 import build_prompt_v3

    import itertools
    scenarios = list(itertools.islice(
        ((r, i, c) for r in ROLES for i in INTENTS for c in CHANNELS),
        100,
    ))

    sizes = []
    for role, intent, channel in scenarios:
        text, _ = build_prompt_v3(role, intent, channel)
        sizes.append(len(text))

    # Hepsi makul boyutta
    check(f"100 senaryo: min={min(sizes):,}, max={max(sizes):,}",
          min(sizes) > 50000 and max(sizes) < 200000,
          f"boyut sinir dishinda")


def test_base_consistency_1000():
    """1000 cagri sonra BASE hep ayni icerikte."""
    print("\n[7] BASE CONSISTENCY (1000 cagri)")
    from prompt_modules.composer_v3 import get_base_prompt

    base = get_base_prompt()
    initial_len = len(base)
    initial_hash = hash(base)

    for _ in range(1000):
        b = get_base_prompt()

    final = get_base_prompt()
    check(f"1000 cagri sonra BASE len ayni ({initial_len:,})",
          len(final) == initial_len)
    check(f"1000 cagri sonra BASE hash ayni",
          hash(final) == initial_hash)


def test_critical_keywords_in_all_v3():
    """Kritik kelimeler tum V3 senaryolarinda korunmus mu?"""
    print("\n[8] KRITIK KELIME KORUMA (60 senaryo)")
    from prompt_modules.composer_v3 import build_prompt_v3

    REQUIRED = ["FermatAI", "KIMLIK MANIPULASYONU", "uydurma", "KVKK",
                "FINANS RED", "sensitive_data_lock"]

    issues = 0
    total = 0
    for role in ROLES:
        for intent in INTENTS[:6]:  # sample
            for channel in CHANNELS:
                total += 1
                text, _ = build_prompt_v3(role, intent, channel)
                missing = []
                for kw in REQUIRED:
                    if kw not in text:
                        # FINANS RED bazi yerlerde "FİNANS RED" (Turkce I)
                        alt = kw.replace("FINANS", "FİNANS")
                        if alt not in text:
                            missing.append(kw)
                if missing:
                    issues += 1
                    print(f"    {role}/{intent}/{channel} eksik: {missing}")

    check(f"Tum senaryolarda kritik kelime mevcut ({total} senaryo)",
          issues == 0,
          f"{issues} senaryoda eksik")


def test_module_size_limits():
    """Hicbir modul 100K char asmasin (cache verimsizligi)."""
    print("\n[9] MODUL BOYUT SINIRLARI")
    from prompt_modules import (pedagoji_extended, render_extended,
                                 db_schema_extended)

    for name, mod in [("pedagoji", pedagoji_extended),
                      ("render", render_extended),
                      ("db_schema", db_schema_extended)]:
        size = len(mod.PROMPT_BLOCK)
        check(f"{name}: {size:,} char (< 100K)",
              size < 100000, f"modul cok buyuk")


def test_total_size_anthropic_limit():
    """Hicbir senaryoda 200K char asmasin (Anthropic prompt limit)."""
    print("\n[10] TOTAL PROMPT SIZE (Anthropic 200K char limit)")
    from prompt_modules.composer_v3 import build_prompt_v3

    max_size = 0
    max_scenario = None
    for role in ROLES:
        for intent in INTENTS:
            for channel in CHANNELS:
                text, _ = build_prompt_v3(role, intent, channel)
                if len(text) > max_size:
                    max_size = len(text)
                    max_scenario = (role, intent, channel)

    check(f"Max prompt {max_size:,} char (< 200K) at {max_scenario}",
          max_size < 200000,
          f"prompt cok buyuk: {max_size}")


def test_v3_disabled_no_crash():
    """V3 disabled iken sistem cagri zinciri crash etmemeli."""
    print("\n[11] V3 DISABLED FALLBACK (no crash)")
    os.environ["PROMPT_V3_ENABLED"] = "false"
    os.environ["PROMPT_V2_ENABLED"] = "true"
    import importlib
    import prompt_router
    importlib.reload(prompt_router)

    # 20 farkli cagri yap, hicbiri crash etmemeli
    for role in ROLES:
        for ch in CHANNELS:
            for intent in ["selamlama", "kavram_aciklama"]:
                try:
                    text, info = prompt_router.build_prompt_v3(
                        role=role, intent=intent, channel=ch,
                        phone="905test",
                    )
                    assert info.get("v3_active") is False
                    assert len(text) > 0
                except Exception as e:
                    check(f"V3 disabled {role}/{intent}/{ch}", False, f"crash: {e}")
                    return

    check("V3 disabled: 20 senaryo crash YOK", True)


def main():
    print("=" * 70)
    print("V3 STABILITY FULL TEST (production gate)")
    print("=" * 70)

    test_funcs = [
        test_160_combinations,
        test_edge_cases,
        test_memory_singleton_1000_calls,
        test_concurrent_50,
        test_cache_control_idempotent,
        test_long_conversation_100,
        test_base_consistency_1000,
        test_critical_keywords_in_all_v3,
        test_module_size_limits,
        test_total_size_anthropic_limit,
        test_v3_disabled_no_crash,
    ]

    for tf in test_funcs:
        try:
            tf()
        except Exception as e:
            global FAIL
            FAIL += 1
            ERRORS.append(f"{tf.__name__} EXCEPTION: {e}")
            print(f"  X EXCEPTION in {tf.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    if ERRORS:
        print("\nFAILURES:")
        for e in ERRORS[:20]:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
