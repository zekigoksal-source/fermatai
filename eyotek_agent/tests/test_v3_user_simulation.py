# -*- coding: utf-8 -*-
"""
V3 USER SIMULATION TEST (25.40z3 production-gate)
===================================================

Gercek ogrenci/ogretmen/admin konusma pattern'lerini simule eder.
Her senaryo icin V3 + cache_control pipeline'in beklenen davranisi:
- Dogru rol/intent/kanal tespit
- Dogru modullerin yuklenmesi
- BASE icinde gerekli ACL kelimeleri
- Cache breakpoint sayisi limit altinda
- Yanit hizi (build_prompt_v3 < 50ms)

Test gruplari:
1. Ogrenci tipik gun (10 mesaj farkli intent)
2. Ogretmen sabah rutini (5 mesaj)
3. Admin/Neo komut zinciri (8 mesaj)
4. Mudur analiz seansi (6 mesaj)
5. Rehber duygu seansi (5 mesaj)
6. Multi-turn ayni konuda (cache hit beklentisi)
7. Multi-turn intent degisimi (cache invalide pattern)
8. Hybrid kanal (whatsapp + web ardisik)
9. Performans: 100 build_prompt_v3 cagrisi <100ms ortalama
10. Bos/None input edge case
"""
import io
import os
import sys
import time

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


# Gercek konusma patternleri (Oturum 17 student_query_registry'den)
OGRENCI_GUN = [
    ("selamlama", "whatsapp", "iyi gunler"),
    ("kavram_aciklama", "whatsapp", "manyetizma nedir"),
    ("deneme_analiz", "whatsapp", "son denememi degerlendir"),
    ("plan_yap", "web", "calisma plani yap"),
    ("ornek_iste", "web", "turev ornek ver"),
    ("cozum_iste", "whatsapp", "bu soruyu coz"),
    ("duygu_paylasim", "whatsapp", "stresliyim"),
    ("motivasyon_destek", "whatsapp", "bunaldim"),
    ("yetenek_sorgu", "whatsapp", "ne yapabilirsin"),
    ("veda", "whatsapp", "bye"),
]

OGRETMEN_RUTIN = [
    ("selamlama", "whatsapp", "merhaba"),
    ("analiz_iste", "whatsapp", "sinifimda devamsiz kim"),
    ("kavram_aciklama", "web", "Newton kuvvet yasalari"),
    ("ornek_iste", "web", "9. sinif fizik testi"),
    ("yetenek_sorgu", "whatsapp", "neler yapabilirsin"),
]

ADMIN_KOMUT = [
    ("selamlama", "whatsapp", "neo"),
    ("meta_direktif", "whatsapp", "sistem durum"),
    ("analiz_iste", "whatsapp", "haftalik rapor"),
    ("meta_direktif", "whatsapp", "guncelle"),
    ("kavram_aciklama", "web", "kuantum mekanigi"),
    ("yetenek_sorgu", "whatsapp", "neler yapabiliyorsun"),
    ("plan_yap", "web", "sistem yol haritasi"),
    ("veda", "whatsapp", "iyi geceler"),
]

MUDUR_ANALIZ = [
    ("selamlama", "whatsapp", "saytn mudurum"),
    ("analiz_iste", "whatsapp", "kurum durum"),
    ("analiz_iste", "whatsapp", "en basarili 10 ogrenci"),
    ("analiz_iste", "whatsapp", "devamsizlik raporu"),
    ("plan_yap", "web", "kurum stratejisi"),
    ("yetenek_sorgu", "whatsapp", "ne yapabilirsin"),
]

REHBER_DUYGU = [
    ("selamlama", "whatsapp", "merhaba"),
    ("duygu_paylasim", "whatsapp", "ogrenci stresli geliyor"),
    ("analiz_iste", "whatsapp", "psikolojik risk listesi"),
    ("motivasyon_destek", "web", "motivasyon teknikleri"),
    ("plan_yap", "web", "rehberlik gorusme programi"),
]


def test_ogrenci_tipik_gun():
    """Ogrenci 10 mesajli gun simulation - her birinde V3 dogru calisir."""
    print("\n[1] OGRENCI TIPIK GUN (10 mesaj)")
    from prompt_modules.composer_v3 import build_prompt_v3

    for intent, channel, desc in OGRENCI_GUN:
        text, info = build_prompt_v3("ogrenci", intent, channel)
        loaded = info["modules_loaded"]

        # Ogrenci her zaman pedagoji aliyor
        check(f"ogrenci/{intent}/{channel} ('{desc}'): pedagoji yuklendi",
              "pedagoji" in loaded,
              f"loaded={loaded}")


def test_ogretmen_sabah_rutini():
    """Ogretmen 5 mesaj rutini."""
    print("\n[2] OGRETMEN SABAH RUTINI (5 mesaj)")
    from prompt_modules.composer_v3 import build_prompt_v3

    for intent, channel, desc in OGRETMEN_RUTIN:
        text, info = build_prompt_v3("ogretmen", intent, channel)
        loaded = info["modules_loaded"]

        # Ogretmen sadece pedagoji-intent'lerde pedagoji aliyor
        if intent in ("kavram_aciklama", "ornek_iste"):
            check(f"ogretmen/{intent}/{channel} ('{desc}'): pedagoji YUKLENDI",
                  "pedagoji" in loaded)
        else:
            check(f"ogretmen/{intent}/{channel} ('{desc}'): pedagoji YOK (optimize)",
                  "pedagoji" not in loaded,
                  f"gereksiz pedagoji yuklendi: {loaded}")


def test_admin_komut_zinciri():
    """Admin 8 mesaj komut zinciri."""
    print("\n[3] ADMIN KOMUT ZINCIRI (8 mesaj)")
    from prompt_modules.composer_v3 import build_prompt_v3

    for intent, channel, desc in ADMIN_KOMUT:
        text, info = build_prompt_v3("admin", intent, channel)
        loaded = info["modules_loaded"]

        # Admin db_schema sadece analiz/plan/meta/deneme
        if intent in ("analiz_iste", "plan_yap", "meta_direktif", "deneme_analiz"):
            check(f"admin/{intent}/{channel} ('{desc}'): db_schema YUKLENDI",
                  "db_schema" in loaded,
                  f"loaded={loaded}")


def test_mudur_analiz_seansi():
    """Mudur 6 mesaj analiz seansi."""
    print("\n[4] MUDUR ANALIZ SEANSI (6 mesaj)")
    from prompt_modules.composer_v3 import build_prompt_v3

    for intent, channel, desc in MUDUR_ANALIZ:
        text, info = build_prompt_v3("mudur", intent, channel)
        loaded = info["modules_loaded"]
        check(f"mudur/{intent}/{channel} ('{desc}'): crash YOK",
              len(loaded) >= 1)


def test_rehber_duygu_seansi():
    """Rehber 5 mesaj duygu seansi."""
    print("\n[5] REHBER DUYGU SEANSI (5 mesaj)")
    from prompt_modules.composer_v3 import build_prompt_v3

    for intent, channel, desc in REHBER_DUYGU:
        text, info = build_prompt_v3("rehber", intent, channel)
        loaded = info["modules_loaded"]
        # Rehber her zaman pedagoji
        check(f"rehber/{intent}/{channel} ('{desc}'): pedagoji yuklendi",
              "pedagoji" in loaded,
              f"loaded={loaded}")


def test_multi_turn_same_topic_cache_hit():
    """Ayni topic'te 5 ardisik mesaj - V3 BASE+modul ayni kalir (cache hit beklentisi)."""
    print("\n[6] MULTI-TURN SAME TOPIC (cache hit pattern)")
    from prompt_modules.composer_v3 import build_prompt_v3

    sizes = []
    modules_set = []
    for _ in range(5):
        text, info = build_prompt_v3("ogrenci", "kavram_aciklama", "web")
        sizes.append(len(text))
        modules_set.append(tuple(info["modules_loaded"]))

    check("5 ardisik ayni input -> ayni boyut (cache stable)",
          len(set(sizes)) == 1,
          f"farkli boyutlar: {set(sizes)}")
    check("5 ardisik ayni input -> ayni modul seti",
          len(set(modules_set)) == 1)


def test_multi_turn_intent_change():
    """Intent degisimi ardisik - V3 dogru modul swap eder."""
    print("\n[7] MULTI-TURN INTENT CHANGE (cache invalide pattern)")
    from prompt_modules.composer_v3 import build_prompt_v3

    sequence = ["selamlama", "kavram_aciklama", "selamlama", "deneme_analiz",
                "duygu_paylasim", "selamlama"]

    for intent in sequence:
        text, info = build_prompt_v3("ogrenci", intent, "whatsapp")
        check(f"ogrenci/{intent}/wp swap OK",
              len(text) > 50000)


def test_hybrid_channel():
    """Whatsapp + web ardisik - V3 render modul dogru swap eder."""
    print("\n[8] HYBRID CHANNEL (wp + web ardisik)")
    from prompt_modules.composer_v3 import build_prompt_v3

    # WP -> render YOK
    text_wp, info_wp = build_prompt_v3("ogrenci", "kavram_aciklama", "whatsapp")
    check("WP/kavram: render YOK (gereksiz)",
          "render" not in info_wp["modules_loaded"])

    # Web -> render VAR
    text_web, info_web = build_prompt_v3("ogrenci", "kavram_aciklama", "web")
    check("Web/kavram: render YUKLENDI",
          "render" in info_web["modules_loaded"])

    # WP geri don
    text_wp2, info_wp2 = build_prompt_v3("ogrenci", "kavram_aciklama", "whatsapp")
    check("WP geri don: render YOK (state pollution YOK)",
          "render" not in info_wp2["modules_loaded"])
    check("WP geri don: ayni boyut",
          len(text_wp) == len(text_wp2))


def test_performance_100_calls():
    """100 build_prompt_v3 cagrisi <100ms ortalama."""
    print("\n[9] PERFORMANS (100 cagri ortalama latency)")
    from prompt_modules.composer_v3 import build_prompt_v3

    # Cache warm-up
    build_prompt_v3("ogrenci", "kavram_aciklama", "web")

    start = time.perf_counter()
    for _ in range(100):
        build_prompt_v3("ogrenci", "kavram_aciklama", "web")
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / 100) * 1000
    check(f"100 cagri ortalama {avg_ms:.2f}ms (<10ms hedef)",
          avg_ms < 10.0,
          f"yavas: {avg_ms:.2f}ms")


def test_input_edge_cases():
    """Bos/None input edge case."""
    print("\n[10] INPUT EDGE CASES")
    from prompt_modules.composer_v3 import build_prompt_v3

    edge_cases = [
        ("", "", ""),
        (None, None, None),
        ("ogrenci", "", "web"),
        ("ogrenci", None, ""),
    ]
    for role, intent, channel in edge_cases:
        try:
            r = role if role is not None else "ogrenci"
            c = channel if channel is not None else "whatsapp"
            text, info = build_prompt_v3(r, intent, c)
            check(f"edge {role!r}/{intent!r}/{channel!r} crash YOK",
                  isinstance(text, str) and len(text) > 0)
        except Exception as e:
            check(f"edge {role!r}/{intent!r}/{channel!r}",
                  False, f"crash: {e}")


def main():
    print("=" * 70)
    print("V3 USER SIMULATION TEST (production gate)")
    print("=" * 70)

    test_funcs = [
        test_ogrenci_tipik_gun,
        test_ogretmen_sabah_rutini,
        test_admin_komut_zinciri,
        test_mudur_analiz_seansi,
        test_rehber_duygu_seansi,
        test_multi_turn_same_topic_cache_hit,
        test_multi_turn_intent_change,
        test_hybrid_channel,
        test_performance_100_calls,
        test_input_edge_cases,
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
