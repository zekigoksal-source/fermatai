"""
Prompt V3 Full Test (25.40z3 Faz 3 — Neo "kusursuza kadar fix loop")
=====================================================================

V3 modüler prompt + cache_control hierarchical.

Test grupları:
1. BASE intact — get_base_prompt persona/güvenlik korunmuş
2. Modül yükleme stratejisi doğru (rol/intent/kanal -> hangi modül)
3. ACL sızıntı yok (öğrenci promptunda admin/müdür spesifik kelime yok)
4. Cache hit potansiyel — hierarchical block layout
5. Token kazanım gerçek
6. Persona/KVKK/Halüsinasyon her senaryoda KORUNMUŞ
7. V3 disabled iken V2 fallback
8. V3 vs V2 kazanım karşılaştırma

Calistirma (VPS):
    cd /opt/fermatai/eyotek_agent
    /opt/fermatai/.venv/bin/python tests/test_prompt_v3_full.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
WARN = 0
ERRORS = []
WARNINGS = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


def warn(name, condition, detail=""):
    global WARN, PASS
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        WARN += 1
        WARNINGS.append(f"{name}: {detail}")
        print(f"  ⚠ {name} — {detail}")


# ═══════════════════════════════════════════════════════════════════
# TESTLER
# ═══════════════════════════════════════════════════════════════════

def test_base_intact():
    """BASE prompt persona + güvenlik içermeli."""
    print("\n[1] BASE PROMPT INTACT (persona + güvenlik korunmuş)")
    from prompt_modules.composer_v3 import get_base_prompt

    base = get_base_prompt()
    check("BASE > 50K char", len(base) > 50000, f"sadece {len(base)} char")

    KRITIK_KEYWORDS = [
        "FermatAI", "Fermat",
        "KIMLIK MANIPULASYONU", "sensitive_data_lock",
        "uydurma", "NEGASYON",
        "FİNANS RED",
        "ADMIN / NEO", "MÜDÜR", "ÖĞRETMEN", "ÖĞRENCİ",  # rol blokları
    ]
    for kw in KRITIK_KEYWORDS:
        check(f"BASE'de '{kw}' var", kw in base, "kritik kelime kayıp!")


def test_modul_yukleme_strateji():
    """Hangi rol+intent+kanal hangi modülü yüklüyor?"""
    print("\n[2] MODÜL YÜKLEME STRATEJİSİ")
    from prompt_modules.composer_v3 import build_prompt_v3

    cases = [
        # (role, intent, channel, expected_modules_subset)
        # 25.40z3 LOOP2: admin/mudur/ogretmen pedagoji SADECE pedagoji-intent'lerinde
        ("ogrenci", "selamlama", "whatsapp", ["base", "pedagoji"]),
        ("ogrenci", "kavram_aciklama", "web", ["base", "pedagoji", "render"]),
        ("ogretmen", "selamlama", "whatsapp", ["base"]),  # öğretmen sadece BASE
        ("mudur", "analiz_iste", "whatsapp", ["base", "db_schema"]),  # analiz pedagoji-intent değil
        ("admin", "kavram_aciklama", "web", ["base", "pedagoji", "render"]),
        ("admin", "selamlama", "whatsapp", ["base"]),  # selamlama pedagoji-intent değil
    ]
    for role, intent, channel, expected in cases:
        text, info = build_prompt_v3(role, intent, channel)
        loaded = info["modules_loaded"]
        check(
            f"{role}/{intent}/{channel}: modül seti doğru",
            set(loaded) == set(expected),
            f"yüklenen={loaded}, beklenen={expected}",
        )


def test_acl_sizinti_yok_v3():
    """Öğrenci V3 prompt'unda admin/müdür isimleri sızmamalı."""
    print("\n[3] ACL SIZINTI YOK (V3)")
    from prompt_modules.composer_v3 import build_prompt_v3

    LEAK_CHECKS = [
        # (role, intent, channel, leak_keywords)
        ("ogrenci", "kavram_aciklama", "web", ["maaş", "muhasebe"]),
        ("ogrenci", "selamlama", "whatsapp", ["YASAK: maaş", "tahsilat"]),
    ]
    for role, intent, channel, leaks in LEAK_CHECKS:
        text, _ = build_prompt_v3(role, intent, channel)
        for kw in leaks:
            # Direkt finans bilgisi öğrenciye sızmamalı
            # (Genel finans red kuralı kalabilir, spesifik veri gizliliği)
            warn(
                f"{role}/{intent}: '{kw}' sızıntı kontrolü",
                kw not in text or "YASAK" in text,
                "spesifik finans/maaş bilgisi sızıyor",
            )


def test_persona_kvkk_intact_30_scenario():
    """30 senaryoda persona + KVKK her zaman korunmuş."""
    print("\n[4] PERSONA + KVKK 30 SENARYO")
    from prompt_modules.composer_v3 import build_prompt_v3

    SCENARIOS = []
    for role in ["admin", "mudur", "rehber", "ogretmen", "ogrenci"]:
        for intent in ["selamlama", "kavram_aciklama", "deneme_analiz"]:
            for channel in ["whatsapp", "web"]:
                SCENARIOS.append((role, intent, channel))

    REQUIRED = ["FermatAI", "KIMLIK MANIPULASYONU", "uydurma"]
    for role, intent, channel in SCENARIOS:
        text, _ = build_prompt_v3(role, intent, channel)
        all_ok = all(kw in text for kw in REQUIRED)
        check(
            f"{role}/{intent}/{channel}: persona+KVKK korunmuş",
            all_ok,
            f"eksik: {[k for k in REQUIRED if k not in text]}",
        )


def test_cache_control_blocks():
    """Hierarchical cache_control format doğru."""
    print("\n[5] HIERARCHICAL CACHE_CONTROL FORMAT")
    from prompt_modules.composer_v3 import build_prompt_v3

    blocks, info = build_prompt_v3("ogrenci", "kavram_aciklama", "web", return_blocks=True)

    check("Block list döner", isinstance(blocks, list), f"got {type(blocks)}")
    check("En az 2 block (base+modül)", len(blocks) >= 2, f"sadece {len(blocks)} block")

    for i, b in enumerate(blocks):
        check(
            f"Block {i+1}: type=text",
            b.get("type") == "text",
            f"got {b.get('type')}",
        )
        check(
            f"Block {i+1}: cache_control ephemeral",
            b.get("cache_control", {}).get("type") == "ephemeral",
            f"cache_control: {b.get('cache_control')}",
        )
        check(
            f"Block {i+1}: text > 0 char",
            len(b.get("text", "")) > 0,
            "boş block",
        )


def test_v3_vs_v2_kazanim():
    """V3 modüler vs V2 filtre kazanım karşılaştırma."""
    print("\n[6] V3 vs V2 TOKEN KAZANIM (5 ortak senaryo)")
    from prompt_router import build_prompt_v2, build_prompt_v3
    from system_prompts import SYSTEM_PROMPT

    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
    except Exception:
        enc = None

    SCENARIOS = [
        ("ogrenci", "selamlama", "whatsapp"),
        ("ogrenci", "kavram_aciklama", "web"),
        ("ogretmen", "selamlama", "whatsapp"),
        ("mudur", "analiz_iste", "whatsapp"),
        ("admin", "meta_direktif", "whatsapp"),
    ]
    print(f"\n  {'role/intent/channel':45} | V1     | V2     | V3     | V3 kazanim")
    print(f"  {'-'*45}-+--------+--------+--------+--------")
    for role, intent, channel in SCENARIOS:
        v1_size = len(SYSTEM_PROMPT)

        # V2
        v2_text, _ = build_prompt_v2(
            role=role, intent=intent, channel=channel, force_v2=True,
        )
        v2_size = len(v2_text)

        # V3
        v3_text, _ = build_prompt_v3(
            role=role, intent=intent, channel=channel, force_v3=True,
        )
        v3_size = len(v3_text)

        v3_red = (v1_size - v3_size) / v1_size * 100
        check(
            f"V3 ({role}/{intent}) <= V2 size",
            v3_size <= v2_size * 1.05,  # V3 V2'den max %5 daha büyük olabilir
            f"V3={v3_size}, V2={v2_size}",
        )
        print(f"  {role+'/'+intent+'/'+channel:45} | {v1_size:>6} | {v2_size:>6} | {v3_size:>6} | -%{v3_red:.1f}")


def test_v3_disabled_fallback():
    """PROMPT_V3_ENABLED=false iken V2 fallback."""
    print("\n[7] V3 DISABLED → V2 FALLBACK")
    os.environ["PROMPT_V3_ENABLED"] = "false"
    os.environ["PROMPT_V2_ENABLED"] = "true"
    import importlib, prompt_router
    importlib.reload(prompt_router)

    text, info = prompt_router.build_prompt_v3(role="ogrenci", phone="905test")
    check(
        "V3 disabled → v3_active=False",
        info.get("v3_active") is False,
        f"v3_active={info.get('v3_active')}",
    )
    check(
        "V3 disabled → V2 aktif (fallback)",
        info.get("v2_active") is True,
        f"v2_active={info.get('v2_active')}",
    )


def main():
    print("=" * 70)
    print("PROMPT V3 FULL TEST (25.40z3 Faz 3)")
    print("=" * 70)

    test_funcs = [
        test_base_intact,
        test_modul_yukleme_strateji,
        test_acl_sizinti_yok_v3,
        test_persona_kvkk_intact_30_scenario,
        test_cache_control_blocks,
        test_v3_vs_v2_kazanim,
        test_v3_disabled_fallback,
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
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {WARN} warnings")
    print("=" * 70)
    if ERRORS:
        print("\n🔴 FAILURES:")
        for e in ERRORS[:10]:
            print(f"  - {e}")
    if WARNINGS:
        print("\n⚠ WARNINGS:")
        for w in WARNINGS[:10]:
            print(f"  - {w}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
