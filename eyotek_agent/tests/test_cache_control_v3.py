"""
Cache Control V3 Test (25.40z3 Faz 3 + Cache)
==============================================

V3 hierarchical cache_control entegrasyon testleri.

Test grupları:
1. _build_system_blocks helper davranışları (V3 None, 1, 2, 3+ blok)
2. Max 3 system breakpoint garanti (tools 4. breakpoint için yer)
3. BASE her zaman ayrı blok (en uzun, en stabil)
4. dynamic_context her zaman SON blok
5. Tüm bloklarda cache_control: ephemeral
6. V3 fallback (composer hata) → legacy 2-block davranışı
7. Anthropic API contract: type=text, text>0, cache_control format

Calistirma (VPS):
    cd /opt/fermatai/eyotek_agent
    /opt/fermatai/.venv/bin/python tests/test_cache_control_v3.py
"""
import io
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows encoding fix
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
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


# ═══════════════════════════════════════════════════════════════════
# TESTLER
# ═══════════════════════════════════════════════════════════════════

def test_v3_none_legacy_2block():
    """V3 None → legacy 2-block (prompt + dynamic)."""
    print("\n[1] V3 None → legacy 2-block davranışı")
    from fermat_core_agent import _build_system_blocks

    blocks = _build_system_blocks(None, "BASE_PROMPT", "DYNAMIC_CTX")
    check("2 blok döner", len(blocks) == 2, f"got {len(blocks)}")
    check("Block 1 = prompt", blocks[0]["text"] == "BASE_PROMPT")
    check("Block 2 = dynamic", blocks[1]["text"] == "DYNAMIC_CTX")
    check("Block 1 cache_control ephemeral",
          blocks[0]["cache_control"]["type"] == "ephemeral")
    check("Block 2 cache_control ephemeral",
          blocks[1]["cache_control"]["type"] == "ephemeral")


def test_v3_empty_list_legacy_2block():
    """V3 boş list → legacy 2-block (defensive)."""
    print("\n[2] V3 [] (boş list) → legacy 2-block")
    from fermat_core_agent import _build_system_blocks

    blocks = _build_system_blocks([], "BASE", "DYN")
    check("2 blok (boş list fallback)", len(blocks) == 2)
    check("Block 1 = BASE fallback", blocks[0]["text"] == "BASE")


def test_v3_single_block():
    """V3 sadece BASE (1 blok) → 2 breakpoint (BASE + dynamic)."""
    print("\n[3] V3 1 blok (sadece BASE) → BASE + dynamic")
    from fermat_core_agent import _build_system_blocks

    v3 = [{"type": "text", "text": "BASE_TEXT", "cache_control": {"type": "ephemeral"}}]
    blocks = _build_system_blocks(v3, "fallback_unused", "DYN_CTX")
    check("2 blok döner", len(blocks) == 2)
    check("Block 1 = V3 BASE", blocks[0]["text"] == "BASE_TEXT")
    check("Block 2 = dynamic", blocks[1]["text"] == "DYN_CTX")
    check("Fallback prompt KULLANILMADI",
          blocks[0]["text"] != "fallback_unused",
          "V3 varken fallback'e düştü")


def test_v3_two_blocks():
    """V3 BASE + 1 extra (2 blok) → 3 breakpoint."""
    print("\n[4] V3 2 blok (BASE+pedagoji) → 3 breakpoint")
    from fermat_core_agent import _build_system_blocks

    v3 = [
        {"type": "text", "text": "BASE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "PEDAGOJI", "cache_control": {"type": "ephemeral"}},
    ]
    blocks = _build_system_blocks(v3, "fallback", "DYN")
    check("3 blok döner", len(blocks) == 3)
    check("Block 1 = BASE", blocks[0]["text"] == "BASE")
    check("Block 2 = PEDAGOJI (ayrı kalmış)", blocks[1]["text"] == "PEDAGOJI")
    check("Block 3 = dynamic", blocks[2]["text"] == "DYN")


def test_v3_three_blocks_concat():
    """V3 BASE + 2 extra (3 blok) → 3 breakpoint (extras concat)."""
    print("\n[5] V3 3 blok (BASE+pedagoji+render) → BASE + extras_concat + dynamic")
    from fermat_core_agent import _build_system_blocks

    v3 = [
        {"type": "text", "text": "BASE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "PEDAGOJI", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "RENDER", "cache_control": {"type": "ephemeral"}},
    ]
    blocks = _build_system_blocks(v3, "fallback", "DYN")
    check("3 blok döner (concat)", len(blocks) == 3)
    check("Block 1 = BASE ayrı", blocks[0]["text"] == "BASE")
    check("Block 2 = PEDAGOJI+RENDER concat",
          blocks[1]["text"] == "PEDAGOJIRENDER")
    check("Block 3 = dynamic", blocks[2]["text"] == "DYN")


def test_v3_four_blocks_concat():
    """V3 BASE + 3 extra (4 blok) → 3 breakpoint (BASE + extras_concat + dynamic).

    KRITIK: ogrenci/kavram_aciklama/web → BASE+pedagoji+render+db_schema = 4 blok.
    Ama wait, db_schema ogrenciye yüklenmez. En kötü case admin/kavram/web →
    BASE+pedagoji+render = 3 blok. Yine de defensive test.
    """
    print("\n[6] V3 4 blok → BASE + 3'lü extras_concat + dynamic (3 breakpoint)")
    from fermat_core_agent import _build_system_blocks

    v3 = [
        {"type": "text", "text": "BASE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "PED", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "REN", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "DB", "cache_control": {"type": "ephemeral"}},
    ]
    blocks = _build_system_blocks(v3, "fallback", "DYN")
    check("3 blok (max breakpoint korundu)", len(blocks) == 3)
    check("Block 2 = PED+REN+DB concat",
          blocks[1]["text"] == "PEDRENDB",
          f"got {blocks[1]['text']}")


def test_max_3_breakpoint_garanti():
    """ASLA 3'ten fazla system breakpoint döndürme (tools 4. için)."""
    print("\n[7] Max 3 system breakpoint garantisi (tools yer kalsın)")
    from fermat_core_agent import _build_system_blocks

    # Çok büyük V3 listesi
    v3 = [{"type": "text", "text": f"M{i}", "cache_control": {"type": "ephemeral"}}
          for i in range(10)]
    blocks = _build_system_blocks(v3, "f", "D")
    check("10 modüllü V3 → 3 blok max", len(blocks) <= 3, f"got {len(blocks)}")
    cache_count = sum(1 for b in blocks if b.get("cache_control"))
    check("3 cache breakpoint max",
          cache_count <= 3,
          f"got {cache_count} breakpoint")


def test_dynamic_always_last():
    """dynamic_context her zaman SON blok olmalı."""
    print("\n[8] dynamic_context her zaman SON blok")
    from fermat_core_agent import _build_system_blocks

    cases = [
        (None, "DYN1"),
        ([], "DYN2"),
        ([{"type": "text", "text": "B", "cache_control": {"type": "ephemeral"}}], "DYN3"),
        ([
            {"type": "text", "text": "B", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "X", "cache_control": {"type": "ephemeral"}},
        ], "DYN4"),
    ]
    for v3, dyn in cases:
        blocks = _build_system_blocks(v3, "f", dyn)
        check(f"V3={'None' if v3 is None else len(v3)} → son blok = dynamic",
              blocks[-1]["text"] == dyn,
              f"son blok={blocks[-1]['text']}")


def test_anthropic_api_contract():
    """Tüm bloklar Anthropic API contract'ına uygun (type=text, text>0, cache_control)."""
    print("\n[9] Anthropic API contract uyumu")
    from fermat_core_agent import _build_system_blocks

    v3 = [
        {"type": "text", "text": "BASE", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "EXTRA", "cache_control": {"type": "ephemeral"}},
    ]
    blocks = _build_system_blocks(v3, "f", "D")

    for i, b in enumerate(blocks):
        check(f"Block {i+1} type=text", b.get("type") == "text")
        check(f"Block {i+1} text>0", len(b.get("text", "")) > 0)
        check(f"Block {i+1} cache_control type=ephemeral",
              b.get("cache_control", {}).get("type") == "ephemeral")


def test_v3_real_compose_integration():
    """Gerçek composer_v3 ile uçtan uca: ogrenci/kavram/web → 3 modül."""
    print("\n[10] Gerçek composer_v3 ile uçtan uca")
    from prompt_modules.composer_v3 import build_prompt_v3
    from fermat_core_agent import _build_system_blocks

    # Öğrenci kavram açıklama web → BASE + pedagoji + render = 3 blok
    v3_blocks, info = build_prompt_v3(
        "ogrenci", "kavram_aciklama", "web", return_blocks=True,
    )
    check("V3 3 blok döndü (BASE+pedagoji+render)",
          len(v3_blocks) == 3,
          f"got {len(v3_blocks)} blok, modules={info['modules_loaded']}")

    system_blocks = _build_system_blocks(v3_blocks, "fb", "DYN_CTX")
    check("System param 3 blok (concat değil — BASE+1 extra+dynamic)",
          len(system_blocks) == 3)
    check("System block 1 = BASE",
          system_blocks[0]["text"] == v3_blocks[0]["text"])
    check("System block 3 = DYN_CTX",
          system_blocks[2]["text"] == "DYN_CTX")


def test_token_savings_estimate():
    """Cache hit beklenen tasarruf — V3 BASE 76K char ≈ 19K token."""
    print("\n[11] Token tasarruf tahmini")
    from prompt_modules.composer_v3 import get_base_prompt

    base = get_base_prompt()
    base_tokens_approx = len(base) // 4  # ~4 char per token (Türkçe daha yüksek olabilir)
    print(f"  BASE: {len(base):,} char ≈ {base_tokens_approx:,} token")

    # Cache hit: 0.10x maliyet (90% indirim)
    # Cache miss: 1.25x maliyet (write penalty)
    # Net break-even: 1 hit + 1 miss = (0.10 + 1.25) / 2 = 0.675x
    # Yani 2. mesajdan itibaren CACHE LEHE.
    check("BASE ≥ 50K char (cache investment'a değer)",
          len(base) >= 50000,
          f"sadece {len(base)} — cache marjinal kalır")


def main():
    print("=" * 70)
    print("CACHE CONTROL V3 TEST (25.40z3 Faz 3 + Cache)")
    print("=" * 70)

    test_funcs = [
        test_v3_none_legacy_2block,
        test_v3_empty_list_legacy_2block,
        test_v3_single_block,
        test_v3_two_blocks,
        test_v3_three_blocks_concat,
        test_v3_four_blocks_concat,
        test_max_3_breakpoint_garanti,
        test_dynamic_always_last,
        test_anthropic_api_contract,
        test_v3_real_compose_integration,
        test_token_savings_estimate,
    ]

    for tf in test_funcs:
        try:
            tf()
        except Exception as e:
            global FAIL
            FAIL += 1
            ERRORS.append(f"{tf.__name__} EXCEPTION: {e}")
            print(f"  ✗ EXCEPTION in {tf.__name__}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 70)
    if ERRORS:
        print("\n🔴 FAILURES:")
        for e in ERRORS[:15]:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
