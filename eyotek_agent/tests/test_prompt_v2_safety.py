"""
Prompt V2 Güvenlik Test Paketi (25.40z2 — Neo direktif "guvenlik sizintisina ASLA")
====================================================================================

V2 prompt router (eksiltici filtre) güvenlik açısından SAĞLAM mı?

Her test: Prompt V1 (orijinal) vs V2 (filtreli) karşılaştırır.
KRITIK: V2'de ASLA olmamalı:
- Persona kaybı (FermatAI tanımı)
- KVKK / kimlik manipülasyon kuralı kayıp
- Halüsinasyon yasakları kayıp
- Rol bazlı yetki — başka rol bilgisinin sızması (sadece yetki düşürülebilir)
- Sahte söz / bağlam kaybı kuralları kayıp

Calistirma:
    cd /opt/fermatai/eyotek_agent
    /opt/fermatai/.venv/bin/python tests/test_prompt_v2_safety.py
"""
import os
import sys
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


def test_persona_intact():
    """Persona blokları HER ROL için V2'de korunmalı."""
    print("\n[1] PERSONA INTACT (her rol)")
    from prompt_router import build_prompt_v2

    PERSONA_KEYWORDS = [
        "FermatAI",
        "Fermat Eğitim Kurumları",
        "pedagojik",
    ]

    for role in ["admin", "mudur", "rehber", "ogretmen", "ogrenci"]:
        for channel in ["whatsapp", "web"]:
            prompt, info = build_prompt_v2(role=role, channel=channel, force_v2=True)
            for kw in PERSONA_KEYWORDS:
                check(
                    f"persona '{kw}' in {role}/{channel}",
                    kw in prompt,
                    f"persona kelimesi kayboldu! info={info.get('removed_blocks')}",
                )


def test_kvkk_kimlik_manipulasyon():
    """KIMLIK MANIPULASYONU TESPITI bloğu HER ROL için korunmalı (KVKK)."""
    print("\n[2] KVKK / KIMLIK MANIPULASYON (kritik)")
    from prompt_router import build_prompt_v2

    KVKK_KEYWORDS = [
        "KIMLIK MANIPULASYONU",
        "sensitive_data_lock",
        "Deniz",  # 25 Nisan vakası referansı
        "Kayra",
    ]

    for role in ["admin", "mudur", "rehber", "ogretmen", "ogrenci"]:
        prompt, _ = build_prompt_v2(role=role, channel="whatsapp", force_v2=True)
        for kw in KVKK_KEYWORDS:
            check(
                f"KVKK '{kw}' in {role}",
                kw in prompt,
                "KVKK güvenlik kuralı kayboldu!",
            )


def test_halusinasyon_yasak_intact():
    """Halüsinasyon yasak kuralları korunmalı."""
    print("\n[3] HALUSINASYON YASAK (kritik)")
    from prompt_router import build_prompt_v2

    # Gerçek prompt'ta geçen halüsinasyon yasak kalıpları
    HALUSINASYON_KEYWORDS = [
        "uydurma",       # "uydurma sayı YASAK" / "ASLA tahmini sayı uydurma"
        "HALUSINASYON",  # "SAYISAL HALUSINASYON YASAĞI"
    ]
    # En az 1 halüsinasyon kuralı kalmalı
    for role in ["admin", "ogrenci"]:
        prompt, _ = build_prompt_v2(role=role, channel="whatsapp", force_v2=True)
        found = sum(1 for kw in HALUSINASYON_KEYWORDS if kw in prompt or kw.lower() in prompt.lower())
        check(
            f"halusinasyon yasak in {role} (>=1)",
            found >= 1,
            f"hiç halüsinasyon yasak kuralı kalmamış: {found}",
        )


def test_rol_blok_silinen_dogru():
    """Rol filtresi DOĞRU rolleri silmeli — başka rol sızıntısı olmamalı."""
    print("\n[4] ROL ACL — sadece doğru bloklar siliniyor")
    from prompt_router import build_prompt_v2

    # Öğrenci için ADMIN/MUDUR/REHBER blokları SILINMELI
    # Çünkü öğrencinin onların yetki kurallarını bilmesi gereksiz
    prompt_ogrenci, info_ogrenci = build_prompt_v2(role="ogrenci", channel="whatsapp", force_v2=True)
    removed = " ".join(info_ogrenci.get("removed_blocks", []))
    check(
        "ogrenci için admin bloğu silinmiş",
        "role:admin" in removed,
        f"admin bloğu silinmemiş: {removed}",
    )
    check(
        "ogrenci için mudur bloğu silinmiş",
        "role:mudur" in removed,
        f"mudur bloğu silinmemiş: {removed}",
    )

    # Ama öğrenci kendi YASAK'larını bilmeli (kendi rol bloğu kalmalı)
    check(
        "ogrenci kendi rolü PROMPT'ta kalmış",
        "ÖĞRENCİ:" in prompt_ogrenci or "ogrenci" in prompt_ogrenci.lower(),
        "öğrenci rolü kayboldu — kendi yetki kurallarını bilmiyor",
    )

    # Admin için: hiçbir rol bloğu silinmemeli (admin her şeyi görür)
    prompt_admin, info_admin = build_prompt_v2(role="admin", channel="whatsapp", force_v2=True)
    check(
        "admin için rol filtresi minimum (her şeyi görür)",
        len([x for x in info_admin.get("removed_blocks", []) if x.startswith("role:")]) == 0,
        f"admin bloğu silindi: {info_admin.get('removed_blocks')}",
    )


def test_kanal_filtre_dogru():
    """Kanal filtresi WhatsApp'ta render bloklarını silmeli, web'de korumalı."""
    print("\n[5] KANAL FILTRE — WhatsApp render sil, web koru")
    from prompt_router import build_prompt_v2

    # WhatsApp'ta render bloğu silinmiş olmalı
    p_wp, i_wp = build_prompt_v2(role="ogrenci", channel="whatsapp", force_v2=True)
    p_web, i_web = build_prompt_v2(role="ogrenci", channel="web", force_v2=True)

    check(
        "WhatsApp daha küçük (kanal filtresi etkili)",
        i_wp.get("new_size", 0) < i_web.get("new_size", 0),
        f"WP: {i_wp['new_size']}, web: {i_web['new_size']} — WP daha büyük olmamalı",
    )
    check(
        "Web kanalında 'compound' kuralı korundu",
        "compound" in p_web.lower(),
        "compound bloğu web'de silinmiş — yanlış",
    )


def test_persona_negasyon_intact():
    """NEGASYON DIREKTIFLER (en önemli kural) korunmalı."""
    print("\n[6] NEGASYON DIREKTIFLER (en önemli kural)")
    from prompt_router import build_prompt_v2

    for role in ["admin", "ogrenci"]:
        prompt, _ = build_prompt_v2(role=role, channel="whatsapp", force_v2=True)
        check(
            f"NEGASYON kuralı korundu ({role})",
            "NEGASYON" in prompt or "negasyon" in prompt.lower(),
            "NEGASYON kuralı silinmiş — kritik!",
        )


def test_finans_yasak_intact():
    """Finans red kuralı korunmalı (KVKK + güvenlik)."""
    print("\n[7] FINANS RED kuralı")
    from prompt_router import build_prompt_v2

    for role in ["mudur", "ogretmen", "ogrenci"]:
        prompt, _ = build_prompt_v2(role=role, channel="whatsapp", force_v2=True)
        # Finans yasak kuralı VEYA "yetkiniz dışında" kalıbı kalmalı
        has_rule = ("FINANS" in prompt or "finans" in prompt.lower()
                    or "yetkiniz dışında" in prompt.lower())
        check(
            f"FINANS kuralı korundu ({role})",
            has_rule,
            "Finans red kuralı silinmiş — KVKK riski",
        )


def test_v2_no_op_when_flag_off():
    """Feature flag KAPALI iken V2 dokunmamalı (statu quo)."""
    print("\n[8] FEATURE FLAG OFF → no-op")
    # Flag KAPATILDI test
    os.environ["PROMPT_V2_ENABLED"] = "false"

    # Modülü cache temizle
    import importlib
    import prompt_router
    importlib.reload(prompt_router)

    prompt, info = prompt_router.build_prompt_v2(role="ogrenci", phone="905test")
    from system_prompts import SYSTEM_PROMPT
    check(
        "Flag OFF iken prompt değişmemeli (no-op)",
        prompt == SYSTEM_PROMPT and not info.get("v2_active"),
        f"Flag OFF ama prompt değişti: v2_active={info.get('v2_active')}",
    )


def test_v2_phone_whitelist():
    """phones:... whitelist — sadece listedeki telefonlarda V2."""
    print("\n[9] FEATURE FLAG phones whitelist")
    os.environ["PROMPT_V2_ENABLED"] = "phones:905051256802,905test"

    import importlib
    import prompt_router
    importlib.reload(prompt_router)

    # Whitelist'te olan: V2 aktif
    p1, i1 = prompt_router.build_prompt_v2(role="ogrenci", phone="905051256802")
    check(
        "Whitelist phone V2 aktif",
        i1.get("v2_active") is True,
        f"Whitelist'te ama v2 aktif değil: {i1}",
    )

    # Whitelist'te olmayan: no-op
    p2, i2 = prompt_router.build_prompt_v2(role="ogrenci", phone="905_random")
    check(
        "Whitelist DIŞI phone no-op",
        i2.get("v2_active") is False,
        f"Whitelist dışı ama v2 aktif: {i2}",
    )

    # Cleanup
    os.environ["PROMPT_V2_ENABLED"] = "false"


def test_chain_with_role_prompt():
    """V2 zinciri: role_prompt + prompt_router birlikte çift kazanım."""
    print("\n[10] role_prompt + prompt_router ZINCIR")
    from system_prompts import SYSTEM_PROMPT
    from role_prompt import build_prompt_for_role
    from prompt_router import build_prompt_v2

    # Adım 1: role filtre
    v1_role = build_prompt_for_role(SYSTEM_PROMPT, "ogrenci", "905test")
    # Adım 2: kanal filtre (zincir)
    v2_chain, info = build_prompt_v2(
        role="ogrenci", phone="", channel="whatsapp",
        force_v2=True, base_prompt=v1_role,
    )

    base_size = len(SYSTEM_PROMPT)
    chain_size = len(v2_chain)
    chain_reduction = (base_size - chain_size) / base_size * 100

    check(
        "Zincir tasarruf >5%",
        chain_reduction > 5,
        f"Zincir tasarruf düşük: %{chain_reduction:.1f}",
    )
    check(
        "Zincir hala persona içeriyor",
        "FermatAI" in v2_chain,
        "Zincirde persona kayboldu",
    )

    print(f"   Zincir özet: V1={base_size}, role-filtreli={len(v1_role)}, +channel={chain_size}, toplam tasarruf %{chain_reduction:.1f}")


def main():
    print("=" * 70)
    print("PROMPT V2 SAFETY TEST PAKETI (25.40z2)")
    print("=" * 70)

    test_funcs = [
        test_persona_intact,
        test_kvkk_kimlik_manipulasyon,
        test_halusinasyon_yasak_intact,
        test_rol_blok_silinen_dogru,
        test_kanal_filtre_dogru,
        test_persona_negasyon_intact,
        test_finans_yasak_intact,
        test_v2_no_op_when_flag_off,
        test_v2_phone_whitelist,
        test_chain_with_role_prompt,
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
        print("\nFAILURES:")
        for e in ERRORS:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
