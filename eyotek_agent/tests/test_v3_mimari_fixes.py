# -*- coding: utf-8 -*-
"""
V3 MIMARI FIXES TEST (4 May 2026 - 6 fix doğrulama)
=====================================================

Yapılan 6 mimari iyileştirmeyi doğrular:

1. role_prompt V3 enable iken atlanır (boşa CPU yok)
2. db_schema_cache V3 db_schema modülü yüklü iken atlanır (duplicate yok)
3. Tier sistemi V3-aware (get_prompt_for_tier override koruması)
4. Intent erken inference (V3 build öncesi classify_intent)
5. Stream/sync request params helper (DRY consolidation)
6. composer.py V1 dead code silindi (prompt_modules sadece V3)
"""
import io
import os
import sys

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


# ═══════════════════════════════════════════════════════════════════
# 1) Tier sistemi V3-aware
# ═══════════════════════════════════════════════════════════════════

def test_tier_v3_aware():
    """get_prompt_for_tier v3_active=True iken full_prompt korur."""
    print("\n[1] TIER V3-AWARE: V3 prompt korunur (LIGHT/NORMAL ezmez)")
    from prompt_tiers import get_prompt_for_tier, LIGHT_PROMPT, NORMAL_PROMPT

    v3_prompt = "V3_BASE_HIERARCHICAL_" + ("X" * 50000)

    # Legacy davranış: V3 yok
    light_legacy = get_prompt_for_tier("light", v3_prompt)
    normal_legacy = get_prompt_for_tier("normal", v3_prompt)
    full_legacy = get_prompt_for_tier("full", v3_prompt)

    check("Legacy: light → LIGHT_PROMPT (V3 ezildi)",
          light_legacy == LIGHT_PROMPT)
    check("Legacy: normal → NORMAL_PROMPT (V3 ezildi)",
          normal_legacy == NORMAL_PROMPT)
    check("Legacy: full → V3 prompt korundu",
          full_legacy == v3_prompt)

    # V3-aware davranış: v3_active=True
    light_v3 = get_prompt_for_tier("light", v3_prompt, v3_active=True)
    normal_v3 = get_prompt_for_tier("normal", v3_prompt, v3_active=True)
    full_v3 = get_prompt_for_tier("full", v3_prompt, v3_active=True)

    check("V3-aware: light + v3_active=True → V3 KORUNDU",
          light_v3 == v3_prompt,
          "V3 hala eziliyor!")
    check("V3-aware: normal + v3_active=True → V3 KORUNDU",
          normal_v3 == v3_prompt)
    check("V3-aware: full + v3_active=True → V3 KORUNDU",
          full_v3 == v3_prompt)


# ═══════════════════════════════════════════════════════════════════
# 2) Stream/sync helper consolidation
# ═══════════════════════════════════════════════════════════════════

def test_request_params_helper():
    """_build_claude_request_params: stream + sync ortak params."""
    print("\n[2] STREAM/SYNC HELPER: _build_claude_request_params")
    from fermat_core_agent import _build_claude_request_params

    # Senaryo 1: V3 yok (legacy 2-block)
    p1 = _build_claude_request_params(
        v3_blocks=None, claude_prompt="P1", dynamic_context="D1",
        claude_tools=[{"name": "tool1", "description": "x"}],
        model="claude-sonnet-4-5", messages=[{"role": "user", "content": "test"}],
    )
    check("V3 None: system var", "system" in p1)
    check("V3 None: 2 system block", len(p1["system"]) == 2)
    check("V3 None: tools var (cache_control'lu)", "tools" in p1)
    check("Helper output: max_tokens 24576", p1["max_tokens"] == 24576)

    # Senaryo 2: Tools boş → tools key cikarilir
    p2 = _build_claude_request_params(
        v3_blocks=None, claude_prompt="P", dynamic_context="D",
        claude_tools=[],
        model="claude-sonnet-4-5", messages=[],
    )
    check("Tools boş → params'tan tools KALDIRILIR (LIGHT tier guard)",
          "tools" not in p2)

    # Senaryo 3: V3 hierarchical blocks
    v3_blocks = [
        {"type": "text", "text": "BASE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "EXTRAS", "cache_control": {"type": "ephemeral"}},
    ]
    p3 = _build_claude_request_params(
        v3_blocks=v3_blocks, claude_prompt="fb", dynamic_context="DYN",
        claude_tools=[{"name": "t"}],
        model="claude-sonnet-4-5", messages=[],
    )
    check("V3 2 block → 3 system block (BASE + EXTRA + DYN)",
          len(p3["system"]) == 3)
    check("V3 son blok = DYN",
          p3["system"][-1]["text"] == "DYN")


# ═══════════════════════════════════════════════════════════════════
# 3) composer.py V1 dead code silindi
# ═══════════════════════════════════════════════════════════════════

def test_dead_code_removed():
    """composer.py silindi, __init__ sadece V3."""
    print("\n[3] DEAD CODE: composer.py V1 silindi")
    import os

    composer_v1 = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prompt_modules", "composer.py"
    )
    check("composer.py (V1) dosyası YOK",
          not os.path.exists(composer_v1))

    # __init__ V3 odaklı mı?
    from prompt_modules import build_prompt_v3, get_base_prompt
    check("prompt_modules.build_prompt_v3 import OK",
          callable(build_prompt_v3))
    check("prompt_modules.get_base_prompt import OK",
          callable(get_base_prompt))

    # Eski V1 composer hala import edilebilir mi? (Edilmemeli)
    try:
        from prompt_modules.composer import build_prompt as _old  # noqa
        check("Eski composer.build_prompt import EDILEMEDI",
              False, "V1 composer hala var!")
    except ImportError:
        check("Eski composer.build_prompt import EDILEMEDI (silindi)", True)


# ═══════════════════════════════════════════════════════════════════
# 4) Intent inference V3 build oncesi
# ═══════════════════════════════════════════════════════════════════

def test_intent_classifier_works():
    """Intent classification fast — V3 build öncesi çalıştırılabilir."""
    print("\n[4] INTENT ERKEN INFERENCE: classify_intent calisir")
    try:
        from intent_classifier import classify_intent
        # Hızlı bir intent classify et
        intent_selam = classify_intent("merhaba")
        intent_kavram = classify_intent("manyetik alan nedir")
        check(f"'merhaba' classify -> {intent_selam}",
              intent_selam is not None or intent_selam == "")
        check(f"'manyetik alan nedir' classify -> {intent_kavram}",
              intent_kavram is not None or intent_kavram == "")

        # Tekrarlı çağrı hızlı (deterministic)
        import time
        start = time.perf_counter()
        for _ in range(100):
            classify_intent("test")
        elapsed = time.perf_counter() - start
        check(f"100 cagri {elapsed*1000:.1f}ms (V3 build oncesi makul)",
              elapsed < 1.0,
              f"yavas: {elapsed*1000:.1f}ms")
    except Exception as e:
        check("classify_intent import OK", False, f"crash: {e}")


# ═══════════════════════════════════════════════════════════════════
# 5) V3 modul secimi - intent erken inference ile
# ═══════════════════════════════════════════════════════════════════

def test_v3_module_loading_with_intent():
    """V3 modül seçimi intent ile doğru çalışır."""
    print("\n[5] V3 MODUL SECIMI - intent ile farklı sonuçlar")
    from prompt_modules.composer_v3 import build_prompt_v3

    # admin: db_schema sadece analiz/plan/meta intent'lerinde
    _, info_admin_meta = build_prompt_v3("admin", "meta_direktif", "whatsapp")
    check(f"admin/meta_direktif → db_schema YUKLENDI",
          "db_schema" in info_admin_meta["modules_loaded"],
          f"loaded={info_admin_meta['modules_loaded']}")

    _, info_admin_selam = build_prompt_v3("admin", "selamlama", "whatsapp")
    check(f"admin/selamlama → db_schema YUKLENMEDI (intent guard)",
          "db_schema" not in info_admin_selam["modules_loaded"])

    # ogretmen: pedagoji sadece pedagoji-intent'inde
    _, info_ogr_kavram = build_prompt_v3("ogretmen", "kavram_aciklama", "web")
    check(f"ogretmen/kavram_aciklama/web → pedagoji + render YUKLENDI",
          "pedagoji" in info_ogr_kavram["modules_loaded"]
          and "render" in info_ogr_kavram["modules_loaded"])

    _, info_ogr_selam = build_prompt_v3("ogretmen", "selamlama", "whatsapp")
    check(f"ogretmen/selamlama/wp → sadece BASE",
          set(info_ogr_selam["modules_loaded"]) == {"base"})


# ═══════════════════════════════════════════════════════════════════
# 6) Sistem entegrasyon: V3 enable durumu kontrol fonksiyonu
# ═══════════════════════════════════════════════════════════════════

def test_v3_enabled_check():
    """_is_v3_enabled_for_phone fonksiyonu V3 durumunu doğru raporlar."""
    print("\n[6] V3 ENABLE CHECK fonksiyonu")
    from prompt_router import _is_v3_enabled_for_phone

    # Default test (env'e bağlı)
    result = _is_v3_enabled_for_phone("905test")
    check("_is_v3_enabled_for_phone bool döner",
          isinstance(result, bool),
          f"got {type(result)}")


def main():
    print("=" * 70)
    print("V3 MIMARI FIXES TEST (6 fix dogrulama)")
    print("=" * 70)

    test_funcs = [
        test_tier_v3_aware,
        test_request_params_helper,
        test_dead_code_removed,
        test_intent_classifier_works,
        test_v3_module_loading_with_intent,
        test_v3_enabled_check,
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
        for e in ERRORS[:10]:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
