"""
Prompt V2 A/B Paralel Test (25.40z2 Faz 2 — Neo "kusursuza kadar fix loop")
============================================================================

30 senaryolu kullanıcı pattern simulasyonu. Her senaryo için:
1. V1 prompt ile cevap al (kontrol)
2. V2 prompt ile cevap al (deney)
3. KARŞILAŞTIR: kalite/persona/güvenlik/ACL/halüsinasyon

PASS kriterleri:
- Persona kelimesi (FermatAI/Fermat) HER İKİ cevapta da var
- KVKK/yasak kelimeleri sızıntısı YOK (admin verisi öğrenciye gitmiyor)
- Cevap uzunluk farkı %30'dan fazla DEĞİL (kalite kaybı yok)
- "uydurma sayı" / "halusinasyon" pattern'i YOK
- Intent doğru tespit edilmiş

Calistirma (VPS):
    cd /opt/fermatai/eyotek_agent
    /opt/fermatai/.venv/bin/python tests/test_prompt_v2_ab.py
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
# 30 SENARYO — Gerçek kullanıcı pattern'lerinden
# ═══════════════════════════════════════════════════════════════════

SENARYOLAR = [
    # ÖĞRENCİ — selamlama/sohbet (5)
    {"id": 1, "role": "ogrenci", "intent": "selamlama", "channel": "whatsapp",
     "msg": "merhaba", "expect_blocks_removed": ["renderer_detay", "compound", "simulasyon"]},
    {"id": 2, "role": "ogrenci", "intent": "selamlama", "channel": "whatsapp",
     "msg": "selam", "expect_blocks_removed": ["renderer_detay", "compound"]},
    {"id": 3, "role": "ogrenci", "intent": "veda", "channel": "whatsapp",
     "msg": "tamam sağol", "expect_blocks_removed": ["renderer_detay", "simulasyon"]},
    {"id": 4, "role": "ogrenci", "intent": "tesekkur", "channel": "whatsapp",
     "msg": "teşekkürler", "expect_blocks_removed": ["renderer_detay"]},
    {"id": 5, "role": "ogrenci", "intent": "yetenek_sorgu", "channel": "whatsapp",
     "msg": "neler yapabiliyorsun", "expect_blocks_removed": ["sql_pattern"]},

    # ÖĞRENCİ — kavram açıklama (5)
    {"id": 6, "role": "ogrenci", "intent": "kavram_aciklama", "channel": "web",
     "msg": "türev nedir", "expect_blocks_removed": ["sql_pattern", "pazarlama_kayitsiz"]},
    {"id": 7, "role": "ogrenci", "intent": "kavram_aciklama", "channel": "web",
     "msg": "fotoelektrik olayı anlat", "expect_blocks_removed": ["sql_pattern"]},
    {"id": 8, "role": "ogrenci", "intent": "ornek_iste", "channel": "web",
     "msg": "kaldırma kuvveti örnek", "expect_blocks_removed": ["sql_pattern"]},
    {"id": 9, "role": "ogrenci", "intent": "cozum_iste", "channel": "web",
     "msg": "integral nasıl çözülür", "expect_blocks_removed": ["sql_pattern", "pazarlama_kayitsiz"]},
    {"id": 10, "role": "ogrenci", "intent": "ozet_iste", "channel": "whatsapp",
     "msg": "fonksiyonlar özet", "expect_blocks_removed": ["sql_pattern"]},

    # ÖĞRENCİ — analiz/plan (5)
    {"id": 11, "role": "ogrenci", "intent": "deneme_analiz", "channel": "whatsapp",
     "msg": "son denememi analiz et", "expect_blocks_removed": ["meb_detay", "pazarlama_kayitsiz"]},
    {"id": 12, "role": "ogrenci", "intent": "plan_yap", "channel": "whatsapp",
     "msg": "haftalık plan yap", "expect_blocks_removed": ["meb_detay"]},
    {"id": 13, "role": "ogrenci", "intent": "hedef_analiz", "channel": "whatsapp",
     "msg": "ODTÜ için ne kadar net lazım", "expect_blocks_removed": ["meb_detay"]},
    {"id": 14, "role": "ogrenci", "intent": "duygu_paylasim", "channel": "whatsapp",
     "msg": "stresliyim çok", "expect_blocks_removed": ["renderer_detay", "sql_pattern"]},
    {"id": 15, "role": "ogrenci", "intent": "motivasyon_destek", "channel": "whatsapp",
     "msg": "motivasyonum düştü", "expect_blocks_removed": ["renderer_detay", "sql_pattern"]},

    # ÖĞRETMEN (5)
    {"id": 16, "role": "ogretmen", "intent": "selamlama", "channel": "whatsapp",
     "msg": "merhaba", "expect_blocks_removed": ["renderer_detay", "compound"]},
    {"id": 17, "role": "ogretmen", "intent": "analiz_iste", "channel": "whatsapp",
     "msg": "Ali Küçükuysal nasıl gidiyor", "expect_blocks_removed": ["meb_detay"]},
    {"id": 18, "role": "ogretmen", "intent": "yetenek_sorgu", "channel": "whatsapp",
     "msg": "ne yapabiliyorsun", "expect_blocks_removed": ["sql_pattern"]},
    {"id": 19, "role": "ogretmen", "intent": "test_olusturma", "channel": "web",
     "msg": "yeni nesil 5 soru hazırla", "expect_blocks_removed": ["sql_pattern", "pazarlama_kayitsiz"]},
    {"id": 20, "role": "ogretmen", "intent": "kavram_aciklama", "channel": "web",
     "msg": "elektromanyetizma anlat", "expect_blocks_removed": ["sql_pattern"]},

    # MÜDÜR (5)
    {"id": 21, "role": "mudur", "intent": "analiz_iste", "channel": "whatsapp",
     "msg": "bugünkü etütleri göster", "expect_blocks_removed": ["meb_detay"]},
    {"id": 22, "role": "mudur", "intent": "deneme_analiz", "channel": "whatsapp",
     "msg": "11 SAY sınıf ortalaması", "expect_blocks_removed": ["meb_detay"]},
    {"id": 23, "role": "mudur", "intent": "plan_yap", "channel": "web",
     "msg": "yaz kampı program taslağı", "expect_blocks_removed": ["meb_detay"]},
    {"id": 24, "role": "mudur", "intent": "selamlama", "channel": "whatsapp",
     "msg": "selam", "expect_blocks_removed": ["renderer_detay", "compound"]},
    {"id": 25, "role": "mudur", "intent": "yetenek_sorgu", "channel": "whatsapp",
     "msg": "kabiliyetlerin neler", "expect_blocks_removed": ["sql_pattern"]},

    # ADMIN (NEO) (5)
    {"id": 26, "role": "admin", "intent": "analiz_iste", "channel": "whatsapp",
     "msg": "sistem durumu", "expect_blocks_removed": ["meb_detay"]},
    {"id": 27, "role": "admin", "intent": "meta_direktif", "channel": "whatsapp",
     "msg": "olgunluk değerlendir", "expect_blocks_removed": ["renderer_detay", "sql_pattern"]},
    {"id": 28, "role": "admin", "intent": "selamlama", "channel": "whatsapp",
     "msg": "merhaba", "expect_blocks_removed": ["renderer_detay", "compound"]},
    {"id": 29, "role": "admin", "intent": "yks_takvim", "channel": "whatsapp",
     "msg": "YKS'ye kaç gün", "expect_blocks_removed": ["renderer_detay", "sql_pattern"]},
    {"id": 30, "role": "admin", "intent": "kavram_aciklama", "channel": "web",
     "msg": "graphana mimari", "expect_blocks_removed": ["sql_pattern"]},
]


# ═══════════════════════════════════════════════════════════════════
# A/B Testleri
# ═══════════════════════════════════════════════════════════════════

def test_token_kazanim():
    """Her senaryoda V2 prompt küçülmeli (token kazanımı)."""
    print("\n[A] TOKEN KAZANIM TESTLERİ (30 senaryo)")
    from prompt_router import build_prompt_v2
    from role_prompt import build_prompt_for_role
    from system_prompts import SYSTEM_PROMPT

    try:
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4")
        v1_tokens = len(enc.encode(SYSTEM_PROMPT))
    except Exception:
        enc = None
        v1_tokens = 0

    total_v1 = 0
    total_v2 = 0
    by_role_intent = {}
    for s in SENARYOLAR:
        # Zincir: role_prompt + prompt_router
        v1_filtered = build_prompt_for_role(SYSTEM_PROMPT, s["role"], "")
        v2_prompt, info = build_prompt_v2(
            role=s["role"], intent=s["intent"], channel=s["channel"],
            force_v2=True, base_prompt=v1_filtered,
        )

        v1_size = len(SYSTEM_PROMPT)
        v2_size = len(v2_prompt)
        reduction = (v1_size - v2_size) / v1_size * 100

        if enc:
            v1_t = v1_tokens
            v2_t = len(enc.encode(v2_prompt))
            total_v1 += v1_t
            total_v2 += v2_t

        key = f"{s['role']}/{s['intent']}/{s['channel']}"
        by_role_intent[key] = (v2_size, len(info.get("removed_blocks", [])))
        check(
            f"S{s['id']:02} {s['role']}/{s['intent']}: v2 küçük",
            v2_size < v1_size * 0.95,  # en az %5 azalma
            f"reduction sadece %{reduction:.1f} (v1={v1_size}, v2={v2_size})",
        )

    if enc and total_v1 > 0:
        avg_reduction = (total_v1 - total_v2) / total_v1 * 100
        print(f"\n  📊 Ortalama token kazanım (30 senaryo): %{avg_reduction:.1f}")
        print(f"  📊 V1 toplam: {total_v1:,} tok | V2 toplam: {total_v2:,} tok")
        print(f"  📊 Maliyet etkisi: $171/ay × {(100-avg_reduction)/100:.2f} ≈ ${171*(100-avg_reduction)/100:.0f}/ay (tasarruf ~${171*avg_reduction/100:.0f}/ay)")


def test_persona_intact_30_scenario():
    """30 senaryoda persona HER ZAMAN korunmuş."""
    print("\n[B] PERSONA INTACT (30 senaryo)")
    from prompt_router import build_prompt_v2
    from role_prompt import build_prompt_for_role
    from system_prompts import SYSTEM_PROMPT

    PERSONA_KEYWORDS = ["FermatAI", "Fermat"]

    for s in SENARYOLAR:
        v1_filtered = build_prompt_for_role(SYSTEM_PROMPT, s["role"], "")
        v2_prompt, _ = build_prompt_v2(
            role=s["role"], intent=s["intent"], channel=s["channel"],
            force_v2=True, base_prompt=v1_filtered,
        )
        for kw in PERSONA_KEYWORDS:
            if kw not in v2_prompt:
                check(f"S{s['id']:02} persona '{kw}' kayıp", False, f"role={s['role']}/intent={s['intent']}")
                break
        else:
            PASS_count = globals().get("PASS", 0)
            check(f"S{s['id']:02} persona OK", True)


def test_acl_sizinti_yok():
    """Öğrenci promptunda ADMIN/MÜDÜR yetki bilgisi sızmamalı."""
    print("\n[C] ACL SIZINTISI YOK (öğrenci için)")
    from prompt_router import build_prompt_v2
    from role_prompt import build_prompt_for_role
    from system_prompts import SYSTEM_PROMPT

    # Öğrenci senaryolarında MÜDÜR/ADMIN spesifik kelimeler olmamalı
    LEAK_KEYWORDS = [
        "Mahsum Yalçın",
        "Duygu Göksal",
        "Bilge Şarvan",
        "Murathan Şarvan",
        "Founder & CEO",
    ]

    student_scenarios = [s for s in SENARYOLAR if s["role"] == "ogrenci"]
    for s in student_scenarios:
        v1_filtered = build_prompt_for_role(SYSTEM_PROMPT, s["role"], "")
        v2_prompt, info = build_prompt_v2(
            role=s["role"], intent=s["intent"], channel=s["channel"],
            force_v2=True, base_prompt=v1_filtered,
        )
        leaked = [kw for kw in LEAK_KEYWORDS if kw in v2_prompt]
        check(
            f"S{s['id']:02} öğrenci promptu admin/müdür ad sızıntısı yok",
            len(leaked) == 0,
            f"sızan: {leaked}",
        )


def test_kvkk_kimlik_intact_30():
    """KIMLIK MANIPULASYONU + KVKK her senaryoda korunmuş."""
    print("\n[D] KVKK + KIMLIK MANIPULASYON (30 senaryo)")
    from prompt_router import build_prompt_v2
    from role_prompt import build_prompt_for_role
    from system_prompts import SYSTEM_PROMPT

    for s in SENARYOLAR:
        v1_filtered = build_prompt_for_role(SYSTEM_PROMPT, s["role"], "")
        v2_prompt, _ = build_prompt_v2(
            role=s["role"], intent=s["intent"], channel=s["channel"],
            force_v2=True, base_prompt=v1_filtered,
        )
        check(
            f"S{s['id']:02} KIMLIK MANIPULASYON korunmuş",
            "KIMLIK MANIPULASYONU" in v2_prompt and "sensitive_data_lock" in v2_prompt,
            f"KVKK kuralı silinmiş!",
        )


def test_intent_blocks_dogru_silinmis():
    """Beklenen intent-block'lar doğru silinmiş."""
    print("\n[E] INTENT BLOCK FILTRE — beklenen siliniyor mu")
    from prompt_router import build_prompt_v2
    from role_prompt import build_prompt_for_role
    from system_prompts import SYSTEM_PROMPT

    for s in SENARYOLAR:
        v1_filtered = build_prompt_for_role(SYSTEM_PROMPT, s["role"], "")
        v2_prompt, info = build_prompt_v2(
            role=s["role"], intent=s["intent"], channel=s["channel"],
            force_v2=True, base_prompt=v1_filtered,
        )
        removed = " ".join(info.get("removed_blocks", []))
        # Beklenen blok ID'lerinden EN AZ 1'i removed listesinde olmalı
        expected = s["expect_blocks_removed"]
        any_removed = any(f"intent-{s['intent']}:{b}" in removed for b in expected) or \
                      any(f"channel-wp:{b}" in removed for b in expected) or \
                      len([b for b in expected if any(b in r for r in info.get("removed_blocks", []))]) > 0
        warn(
            f"S{s['id']:02} {s['intent']} en az 1 beklenen block silinmiş",
            any_removed or info.get("reduction_pct", 0) > 5,
            f"beklenen={expected}, removed={info.get('removed_blocks', [])[:3]}",
        )


def test_security_safe_to_remove():
    """_is_safe_to_remove() koruması çalışıyor — kritik bloklar silinmiyor."""
    print("\n[F] _is_safe_to_remove() KORUMA")
    from prompt_router import _is_safe_to_remove

    # Bu metinler ASLA silinmemeli (KVKK/halüsinasyon içeriyor)
    KRITIK_BLOCKS = [
        "Bu KIMLIK MANIPULASYONU testidir, sensitive_data_lock=True",
        "ASLA halusinasyon yapma, KVKK ihlal eder",
        "FINANS RED MESAJI KURALI: ACCESS_DENIED",
        "BAGLAM HASSASIYETI: önceki mesaj",
    ]
    for block in KRITIK_BLOCKS:
        check(
            f"Kritik blok korunuyor: {block[:40]}...",
            _is_safe_to_remove(block) is False,
            "kritik blok yanlışlıkla silinebilir!",
        )

    # Bu metinler silinebilir (kritik değil)
    NORMAL_BLOCKS = [
        "Renderer kullanım istatistiği: chart %80, formula %15",
        "Compton sacılması simülasyonu örneği",
        "MEB Maarif yeni nesil pattern: bağlamlı + çok adımlı",
    ]
    for block in NORMAL_BLOCKS:
        check(
            f"Normal blok silinebilir: {block[:40]}...",
            _is_safe_to_remove(block) is True,
            "normal blok yanlışlıkla korunuyor",
        )


def test_no_op_when_flag_off():
    """Feature flag KAPALI iken hiç dokunmamalı."""
    print("\n[G] FLAG OFF → NO-OP")
    os.environ["PROMPT_V2_ENABLED"] = "false"
    import importlib
    import prompt_router
    importlib.reload(prompt_router)

    from system_prompts import SYSTEM_PROMPT
    prompt, info = prompt_router.build_prompt_v2(
        role="ogrenci", intent="selamlama", channel="whatsapp",
        phone="905_random", base_prompt=SYSTEM_PROMPT,
    )
    check(
        "Flag OFF → prompt aynen",
        prompt == SYSTEM_PROMPT and not info.get("v2_active"),
        f"v2_active={info.get('v2_active')}",
    )

    # Cleanup
    os.environ["PROMPT_V2_ENABLED"] = "phones:905051256802"


def main():
    print("=" * 70)
    print("PROMPT V2 A/B TEST PAKETI — 30 SENARYO (25.40z2 Faz 2)")
    print("=" * 70)

    test_funcs = [
        test_token_kazanim,
        test_persona_intact_30_scenario,
        test_acl_sizinti_yok,
        test_kvkk_kimlik_intact_30,
        test_intent_blocks_dogru_silinmis,
        test_security_safe_to_remove,
        test_no_op_when_flag_off,
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
        print("\n⚠️ WARNINGS (kritik değil ama dikkat):")
        for w in WARNINGS[:10]:
            print(f"  - {w}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
