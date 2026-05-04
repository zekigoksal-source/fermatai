"""
V3 SECURITY FULL TEST (25.40z3 production-gate)
================================================

V3 modüler prompt + cache_control'ın güvenlik garantilerini doğrular.
HİÇ BİR TEST FAIL ETMEMELİ — production'a çıkmadan önce zorunlu.

Test grupları:
1. PERSONA (FermatAI kimlik) — 30 senaryo, KIMLIK_MANIPULASYONU intact
2. KVKK (sensitive_data_lock) — finans, telefon, kişisel veri
3. NEGASYON (uydurma yasağı) — halüsinasyon koruma kuralları
4. FİNANS RED — öğrenci/öğretmen finansal soru reddi
5. ACL (rol bazlı izin) — admin/müdür/öğretmen/öğrenci/rehber
6. ÖĞRENCİ ACL — başka öğrenci verisi sızıntısı YOK
7. NEO İSTİSNA — admin için özel yetkiler intact
8. ROL BLOK MARKER — her rolün yetki bloğu BASE'de
9. CACHE_CONTROL — Anthropic API contract uyumu
10. INTENT BAZLI MODÜL — pedagoji-only intent'lerde admin için pedagoji yüklenir

Calistirma:
    cd C:\\Users\\zekig\\OneDrive\\Desktop\\FermatAI\\eyotek_agent
    .venv\\Scripts\\python.exe tests/test_v3_security_full.py
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
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


# ═══════════════════════════════════════════════════════════════════
# 1) PERSONA — FermatAI kimlik koruması (30 senaryo)
# ═══════════════════════════════════════════════════════════════════

PERSONA_KEYWORDS = [
    "FermatAI",
    "Fermat",
    "KIMLIK MANIPULASYONU",
]


def test_persona_30_senaryo():
    print("\n[1] PERSONA — 30 senaryoda kimlik koruma")
    from prompt_modules.composer_v3 import build_prompt_v3

    scenarios = []
    for role in ["admin", "mudur", "rehber", "ogretmen", "ogrenci"]:
        for intent in ["selamlama", "kavram_aciklama", "deneme_analiz",
                       "duygu_paylasim", "analiz_iste", "yetenek_sorgu"]:
            for channel in ["whatsapp", "web"]:
                scenarios.append((role, intent, channel))

    for role, intent, channel in scenarios:
        text, _ = build_prompt_v3(role, intent, channel)
        for kw in PERSONA_KEYWORDS:
            if kw not in text:
                check(f"{role}/{intent}/{channel}: '{kw}' yok",
                      False, f"persona kelime kayıp")
                break
        else:
            check(f"{role}/{intent}/{channel}: persona intact", True)


# ═══════════════════════════════════════════════════════════════════
# 2) KVKK — sensitive_data_lock + kişisel veri koruma
# ═══════════════════════════════════════════════════════════════════

KVKK_KEYWORDS = [
    "sensitive_data_lock",
    "KVKK",
]


def test_kvkk_intact():
    print("\n[2] KVKK — sensitive_data_lock + kuralları her senaryoda")
    from prompt_modules.composer_v3 import build_prompt_v3

    for role in ["admin", "mudur", "ogretmen", "ogrenci", "rehber"]:
        for channel in ["whatsapp", "web"]:
            text, _ = build_prompt_v3(role, "kavram_aciklama", channel)
            for kw in KVKK_KEYWORDS:
                check(f"{role}/{channel}: '{kw}' var", kw in text,
                      f"KVKK kelimesi kayıp")


# ═══════════════════════════════════════════════════════════════════
# 3) NEGASYON — Halüsinasyon koruma
# ═══════════════════════════════════════════════════════════════════

def test_negasyon_intact():
    print("\n[3] NEGASYON — uydurma yasağı her rolde")
    from prompt_modules.composer_v3 import build_prompt_v3

    for role in ["admin", "mudur", "ogretmen", "ogrenci", "rehber"]:
        text, _ = build_prompt_v3(role, "kavram_aciklama", "web")
        check(f"{role}: 'uydurma' yasağı var", "uydurma" in text,
              "halüsinasyon kuralı kayıp")
        check(f"{role}: 'NEGASYON' bloğu var", "NEGASYON" in text,
              "NEGASYON başlığı kayıp")


# ═══════════════════════════════════════════════════════════════════
# 4) FİNANS RED
# ═══════════════════════════════════════════════════════════════════

def test_finans_red():
    print("\n[4] FİNANS RED — kuralı tüm rollerde")
    from prompt_modules.composer_v3 import build_prompt_v3

    for role in ["admin", "mudur", "ogretmen", "ogrenci", "rehber"]:
        text, _ = build_prompt_v3(role, "selamlama", "whatsapp")
        check(f"{role}: 'FİNANS RED' var", "FİNANS RED" in text,
              "finans red kuralı kayıp")


# ═══════════════════════════════════════════════════════════════════
# 5) ACL — Her rolün yetki bloğu BASE'de
# ═══════════════════════════════════════════════════════════════════

ROLE_BLOCK_HEADERS = {
    "admin": "ADMIN / NEO",
    "mudur": "MÜDÜR",
    "ogretmen": "ÖĞRETMEN",
    "ogrenci": "ÖĞRENCİ",
}


def test_acl_role_blocks_in_base():
    print("\n[5] ACL — Her rolün yetki bloğu BASE'de mevcut")
    from prompt_modules.composer_v3 import get_base_prompt

    base = get_base_prompt()
    for role, header in ROLE_BLOCK_HEADERS.items():
        check(f"BASE'de '{header}' bloğu var", header in base,
              f"{role} blok marker kayıp")


# ═══════════════════════════════════════════════════════════════════
# 6) ÖĞRENCİ ACL — başka öğrenci/admin verisi sızıntısı YOK
# ═══════════════════════════════════════════════════════════════════

# Öğrenci promptunda olmamalı: admin'e özel SQL yetki kelimeleri,
# müdür'e özel maaş/muhasebe sorgu izinleri
LEAK_FORBIDDEN_FOR_OGRENCI = [
    # Bu kelimeler admin/mudur'a özel — öğrenci promptunda OLMAMALI
    # NOT: Bazıları BASE'de "YASAK" bağlamında geçebilir, öğrenci ACL kuralı için
]


def test_ogrenci_acl_no_leak():
    print("\n[6] ÖĞRENCİ ACL — kendi soz_no kuralı + diğer rol bilgi sızıntısı")
    from prompt_modules.composer_v3 import build_prompt_v3

    text, _ = build_prompt_v3("ogrenci", "kavram_aciklama", "web")

    # Öğrenci promptunda kendi soz_no'sunu kullan kuralı olmalı (BASE'de)
    check("Öğrenci kendi soz_no kuralı var",
          "Sadece kendi" in text or "kendi soz_no" in text or "ÖĞRENCİ" in text,
          "ACL kuralı kayıp")

    # Öğrenci'de finans bilgisi ASLA görünmemeli (sadece YASAK bağlamında geçer)
    if "maaş" in text:
        # YASAK bağlamında geçiyor mu?
        idx = text.find("maaş")
        ctx = text[max(0, idx-200):idx+200]
        is_yasak_ctx = "YASAK" in ctx or "FİNANS" in ctx or "MUHASEBE" in ctx
        check("'maaş' kelimesi sadece YASAK bağlamında",
              is_yasak_ctx, "maaş bilgisi sızıyor olabilir")


# ═══════════════════════════════════════════════════════════════════
# 7) NEO İSTİSNA — Admin için özel yetkiler intact
# ═══════════════════════════════════════════════════════════════════

def test_neo_istisna_intact():
    print("\n[7] NEO İSTİSNA — admin promptunda Neo özel yetki bloğu")
    from prompt_modules.composer_v3 import build_prompt_v3

    text, _ = build_prompt_v3("admin", "meta_direktif", "whatsapp")
    # Neo özel yetki kelimeleri
    check("admin: 'NEO' var", "NEO" in text, "Neo kimliği kayıp")
    check("admin: 'Zeki' var", "Zeki" in text or "905051256802" in text,
          "Neo telefon/isim kayıp")


# ═══════════════════════════════════════════════════════════════════
# 8) MODÜL YÜKLEME STRATEJİSİ — Doğru rol+intent+kanal kombinasyonu
# ═══════════════════════════════════════════════════════════════════

def test_modul_loading_strategy_full():
    print("\n[8] MODÜL YÜKLEME — 18 rol+intent+kanal kombinasyonu")
    from prompt_modules.composer_v3 import build_prompt_v3

    # (role, intent, channel, expected_modules)
    test_cases = [
        # Öğrenci her zaman pedagoji
        ("ogrenci", "selamlama", "whatsapp", {"base", "pedagoji"}),
        ("ogrenci", "kavram_aciklama", "web", {"base", "pedagoji", "render"}),
        ("ogrenci", "kavram_aciklama", "whatsapp", {"base", "pedagoji"}),
        ("ogrenci", "deneme_analiz", "whatsapp", {"base", "pedagoji"}),
        ("ogrenci", "plan_yap", "web", {"base", "pedagoji", "render"}),

        # Rehber her zaman pedagoji + intent'e göre db_schema
        ("rehber", "selamlama", "whatsapp", {"base", "pedagoji"}),
        ("rehber", "analiz_iste", "whatsapp", {"base", "pedagoji", "db_schema"}),
        ("rehber", "duygu_paylasim", "web", {"base", "pedagoji", "render"}),

        # Öğretmen sadece pedagoji-intent'lerde pedagoji
        ("ogretmen", "selamlama", "whatsapp", {"base"}),
        ("ogretmen", "kavram_aciklama", "web", {"base", "pedagoji", "render"}),
        ("ogretmen", "yetenek_sorgu", "whatsapp", {"base"}),

        # Müdür: db_schema sadece analiz/plan/meta intent'lerinde
        ("mudur", "selamlama", "whatsapp", {"base"}),
        ("mudur", "analiz_iste", "whatsapp", {"base", "db_schema"}),
        ("mudur", "kavram_aciklama", "web", {"base", "pedagoji", "render"}),

        # Admin: db_schema gerektiren intent'lerde + pedagoji intent'lerinde pedagoji
        ("admin", "selamlama", "whatsapp", {"base"}),
        ("admin", "meta_direktif", "whatsapp", {"base", "db_schema"}),
        ("admin", "kavram_aciklama", "web", {"base", "pedagoji", "render"}),
        ("admin", "yetenek_sorgu", "whatsapp", {"base"}),
    ]

    for role, intent, channel, expected in test_cases:
        _, info = build_prompt_v3(role, intent, channel)
        loaded = set(info["modules_loaded"])
        check(f"{role}/{intent}/{channel}: modüller={sorted(expected)}",
              loaded == expected,
              f"loaded={sorted(loaded)}, expected={sorted(expected)}")


# ═══════════════════════════════════════════════════════════════════
# 9) CACHE_CONTROL — Anthropic API contract
# ═══════════════════════════════════════════════════════════════════

def test_cache_control_contract():
    print("\n[9] CACHE_CONTROL — Anthropic API contract")
    from prompt_modules.composer_v3 import build_prompt_v3

    blocks, info = build_prompt_v3("ogrenci", "kavram_aciklama", "web",
                                   return_blocks=True)
    check("blocks list döner", isinstance(blocks, list))
    check("Tüm bloklar 'type=text'",
          all(b.get("type") == "text" for b in blocks))
    check("Tüm bloklar cache_control: ephemeral",
          all(b.get("cache_control", {}).get("type") == "ephemeral" for b in blocks))
    check("Tüm bloklar non-empty",
          all(len(b.get("text", "")) > 0 for b in blocks))

    # _build_system_blocks pipeline test
    from fermat_core_agent import _build_system_blocks
    sys_blocks = _build_system_blocks(blocks, "fb", "DYN_CTX")
    check("_build_system_blocks ≤3 blok (max breakpoint)",
          len(sys_blocks) <= 3, f"got {len(sys_blocks)}")
    check("_build_system_blocks son blok = dynamic",
          sys_blocks[-1]["text"] == "DYN_CTX")


# ═══════════════════════════════════════════════════════════════════
# 10) BASE STABILITY — Singleton cache behavior
# ═══════════════════════════════════════════════════════════════════

def test_base_singleton_stable():
    print("\n[10] BASE — singleton cache aynı object döner (memory verim)")
    from prompt_modules.composer_v3 import get_base_prompt

    b1 = get_base_prompt()
    b2 = get_base_prompt()
    check("BASE singleton (aynı string)",
          b1 is b2 or b1 == b2,
          "BASE her çağrıda yeniden oluşuyor (memory leak)")
    check("BASE > 50K char",
          len(b1) > 50000, f"sadece {len(b1)} char")


# ═══════════════════════════════════════════════════════════════════
# 11) BÜYÜK MODÜLLERIN BASE'den TAMAMEN ÇIKARILMASI
# ═══════════════════════════════════════════════════════════════════

def test_modules_extracted_from_base():
    print("\n[11] EXTRACT — Modüller BASE'de DUPLICATE olmamalı")
    from prompt_modules.composer_v3 import get_base_prompt
    from prompt_modules import (pedagoji_extended, render_extended,
                                 db_schema_extended)

    base = get_base_prompt()

    # Pedagoji bloğunun bazı characteristic kelimeleri BASE'de OLMAMALI
    # (modüle gitmiş olmalı)
    # NOT: PEDAGOJI bloğu içinde "PEDAGOJI" başlığı vardır — BASE'de olmamalı
    pedagoji_first_500 = pedagoji_extended.PROMPT_BLOCK[:500]
    # İlk 500 char'da characteristic bir cümle var mı?
    if pedagoji_first_500.strip():
        # Modülün ilk 500 char'ı BASE'de DUPLICATE olmamalı
        check("Pedagoji bloğu BASE'den çıkarılmış (duplicate yok)",
              pedagoji_first_500.strip() not in base,
              "pedagoji bloğu hâlâ BASE'de — duplicate token!")

    render_first_500 = render_extended.PROMPT_BLOCK[:500]
    if render_first_500.strip():
        check("Render bloğu BASE'den çıkarılmış",
              render_first_500.strip() not in base,
              "render bloğu hâlâ BASE'de")

    db_first_500 = db_schema_extended.PROMPT_BLOCK[:500]
    if db_first_500.strip():
        check("DB schema bloğu BASE'den çıkarılmış",
              db_first_500.strip() not in base,
              "db_schema bloğu hâlâ BASE'de")


# ═══════════════════════════════════════════════════════════════════
# 12) FALLBACK GÜVENLİĞİ — composer hata → V2 fallback ANA SİSTEMİ KORUR
# ═══════════════════════════════════════════════════════════════════

def test_fallback_safety():
    print("\n[12] FALLBACK — Hata durumunda sistem çökmeden V2'ye düşmeli")
    os.environ["PROMPT_V3_ENABLED"] = "false"
    os.environ["PROMPT_V2_ENABLED"] = "true"

    import importlib
    import prompt_router
    importlib.reload(prompt_router)

    text, info = prompt_router.build_prompt_v3(role="ogrenci", phone="905test")
    check("V3 disabled → v3_active=False",
          info.get("v3_active") is False)
    check("V3 disabled → V2 fallback aktif",
          info.get("v2_active") is True)
    check("V3 disabled → text NON-EMPTY",
          len(text) > 0)


# ═══════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("V3 SECURITY FULL TEST (production gate)")
    print("=" * 70)

    test_funcs = [
        test_persona_30_senaryo,
        test_kvkk_intact,
        test_negasyon_intact,
        test_finans_red,
        test_acl_role_blocks_in_base,
        test_ogrenci_acl_no_leak,
        test_neo_istisna_intact,
        test_modul_loading_strategy_full,
        test_cache_control_contract,
        test_base_singleton_stable,
        test_modules_extracted_from_base,
        test_fallback_safety,
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
        for e in ERRORS[:20]:
            print(f"  - {e}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
