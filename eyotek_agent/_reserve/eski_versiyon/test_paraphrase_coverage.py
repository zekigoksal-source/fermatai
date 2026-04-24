"""
FermatAI Paraphrase Coverage Test
=================================
Her soru tipini 5-10 farkli ifade tarziyla test eder.
Amac: fast_response veya cloud routing kacirilan, Ollama'ya dusecek tehlikeli sorulari bulmak.

Kurallar:
  - Veri gerektiren her soru → fast_response VEYA cloud (Claude) olmali
  - Ollama'ya SADECE sohbet/motivasyon/konu aciklamasi gitmeli
  - Fast response ciktisi gorsel olarak yuksek kalitede olmali (emoji, bold, liste)
"""

import asyncio
import io
import os
import re
import sys
from typing import Optional

# Windows emoji fix
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# LLM router import
sys.path.insert(0, '.')
from llm_router import classify_complexity

# ═══════════════════════════════════════════════════════════════════════════════
# TEST VERISI — Paraphrased sorular
# ═══════════════════════════════════════════════════════════════════════════════

# Her tuple: (soru, beklenen_sonuc)
# beklenen: "fast" = fast_response yakalamali, "cloud" = Claude'a gitmeli, "local_ok" = Ollama OK

OGRENCI_TESTS = [
    # ── Son Deneme ──
    ("son denemem nasıl", "fast"),
    ("sınav sonucum ne", "fast"),
    ("denemede kaç yaptım", "fast"),
    ("son sınavım nasıl geçti", "fast"),
    ("denemem nasıl gitti", "fast"),
    ("netleri görebilir miyim", "fast"),
    ("deneme sonuçlarıma bakabilir misin", "fast"),
    ("kaçıncı oldum denemede", "fast"),
    ("sıralamam kaç", "fast"),
    ("sonuçlar açıklandı mı", "fast"),

    # ── Kıyaslama ──
    ("son 3 denememi kıyasla", "fast"),
    ("gelişmem nasıl", "fast"),
    ("son denemelerdeki trendim ne", "fast"),
    ("ilerleme kaydettim mi", "fast"),
    ("netlerim artıyor mu", "fast"),
    ("son 5 denememi karşılaştır", "fast"),
    ("grafik göster", "fast"),
    ("gidişatım nasıl", "fast"),

    # ── Zayıf Konular ──
    ("zayıf konularım neler", "fast"),
    ("neye çalışmam lazım", "fast"),
    ("eksik konularım hangileri", "fast"),
    ("nerede hata yapıyorum", "fast"),
    ("hangi konularda zayıfım", "fast"),
    ("en çok hata yaptığım konular", "fast"),
    ("neleri bilmiyorum", "fast"),
    ("konularımı listeler misin", "fast"),

    # ── Güçlü Konular ──
    ("iyi olduğum konular", "fast"),
    ("güçlü yanlarım neler", "fast"),
    ("hangi konularda başarılıyım", "fast"),
    ("en iyi olduğum dersler", "fast"),
    ("güçlü konularımı göster", "fast"),

    # ── Devamsızlık ──
    ("devamsızlığım kaç saat", "fast"),
    ("kaç gün gelmedim", "fast"),
    ("yoklama durumum nasıl", "fast"),
    ("devamsızlık saatim", "fast"),
    ("toplam devamsızlık", "fast"),
    ("kaç ders kaçırdım", "fast"),

    # ── Ders Programı ──
    ("ders programım ne", "fast"),
    ("bu hafta derslerim neler", "fast"),
    ("haftalık programım", "fast"),
    ("hangi günler dersim var", "fast"),
    ("bu haftaki derslerimi göster", "fast"),

    # ── Çalışma Planı ──
    ("bana çalışma programı yap", "fast"),
    ("ne çalışmalıyım", "fast"),
    ("çalışma planı oluştur", "fast"),
    ("haftalık plan yap", "fast"),
    ("planlama yap bana", "fast"),
    ("nasıl çalışayım", "fast"),
    ("günlük çalışma programı istiyorum", "fast"),

    # ── Hedef ──
    ("hedefim ne olmalı", "fast"),
    ("kaç net yapmam lazım", "fast"),
    ("üniversite hedefim nedir", "fast"),
    ("bölüm tercih önerileri", "fast"),
    ("hangi üniversiteye gidebilirim", "fast"),
    ("hedef puanım ne", "fast"),

    # ── Sohbet (Ollama OK) ──
    ("nasılsın", "local_ok"),
    ("bugün hava çok güzel", "local_ok"),
    ("sıkıldım", "local_ok"),
    ("canım ders çalışmak istemiyor", "local_ok"),
    ("motivasyonum düştü", "local_ok"),

    # ── Konu Açıklama (Ollama OK) ──
    ("kaldırma kuvveti nedir", "local_ok"),
    ("türev nasıl alınır", "local_ok"),
    ("mitoz ve mayoz farkı ne", "local_ok"),
    ("osmanlı devleti ne zaman kuruldu", "local_ok"),
    ("logaritma kuralları", "local_ok"),

    # ── Selamlama ──
    ("merhaba", "fast"),
    ("selam", "fast"),
    ("sa", "fast"),
    ("slm", "fast"),
    ("iyi günler", "fast"),

    # ════════════════════════════════════════════════════
    # İMLA HATALI VERSIYONLAR (gerçek kullanıcı deneyimi)
    # ════════════════════════════════════════════════════
    ("son denemem nasıll", "fast"),
    ("sınav sonucum nee", "fast"),
    ("sinav sonucum ne", "fast"),  # ş→s, ı→i
    ("denemem nasil", "fast"),     # ı→i
    ("kacinci oldum", "fast"),     # ç→c, ı→i
    ("gelismem nasil gidiyo", "fast"),
    ("zayif konularim ne", "fast"),  # ı→i kırılır mı
    ("nereye calismam lazim", "fast"),  # ş→s
    ("neye calismam gerekiyor", "fast"),
    ("guclu konularim", "fast"),  # ü→u
    ("iyi oldugum konular neler", "fast"),
    ("devamsizligim kac saat", "fast"),  # ı→i ç→c
    ("kac gun gelmedim", "fast"),
    ("ders programi ne", "fast"),  # ı→i
    ("bu hafta derslerim ne", "fast"),
    ("calisma plani yap", "fast"),  # ş→s ı→i
    ("calisma programi olustur", "fast"),
    ("hedefim nolmali", "fast"),  # bitişik yazım
    ("kac net yapmam lazim", "fast"),
    ("universite hedefim", "fast"),
    ("bolum onerileri", "fast"),
    ("son uc denememi kiyasla", "fast"),  # ü→u, ı→i
    ("son denem nasil gecti", "fast"),  # eksik harf
    ("sinav sonuclarim", "fast"),  # ı→i
    ("nasilim denemelerde", "fast"),
    ("denemlerde durumum ne", "fast"),  # eksik harf
    ("zayif oldugum yerler", "fast"),
    ("hangi konulra calismam lazim", "fast"),  # typo: konulra
    ("devamsizlik kac", "fast"),
    ("ders programimi goster", "fast"),
    ("etüt var mi bu hafta", "fast"),
    ("etut ne zaman", "fast"),
    ("rehberlik gorusmelerim", "fast"),  # ü→u, ş→s
    ("bi calisma programi lazim", "fast"),
    ("calisma plani yapabilir misin", "fast"),
]

OGRETMEN_TESTS = [
    ("ders programım ne", "fast"),
    ("bugün hangi derslerim var", "fast"),
    ("bugünkü programım", "fast"),
    ("bu hafta kaç dersim var", "fast"),
    ("haftalık ders saatim", "fast"),
    ("kaç etüt verdim", "fast"),
    ("etüt istatistiğim", "fast"),
    ("etüt sayım kaç", "fast"),
    ("toplam kaç saat etüt verdim", "fast"),
    ("etüt performansım", "fast"),
    # Sohbet OK
    ("merhaba", "fast"),
    ("nasılsınız", "local_ok"),
    ("iyi günler", "fast"),
]

ADMIN_TESTS = [
    # ── Gün Programı ──
    ("salı günü kimler var", "fast"),
    ("çarşamba hangi hocaların dersi var", "fast"),
    ("cumartesi günü dersleri", "fast"),
    ("pazartesi programı nedir", "fast"),
    ("perşembe gününde kimler ders veriyor", "fast"),
    ("bugün cuma mı ders var mı", "fast"),

    # ── Sınıf Listesi ──
    ("11.sınıf öğrencileri", "fast"),
    ("11 sınıf kimler", "fast"),
    ("11.sınıfları listele", "fast"),
    ("mezun say öğrencileri", "fast"),
    ("lgs öğrencileri kimler", "fast"),
    ("12.sınıfta kaç kişi var", "fast"),
    ("kaç tane 11.sınıf var", "fast"),
    ("kurumdaki sınıfları listele", "fast"),
    ("sınıfları göster", "fast"),
    ("sınıf dağılımı nasıl", "fast"),

    # ── Öğrenci Sayısı ──
    ("kaç öğrenci var", "fast"),
    ("toplam öğrenci sayımız kaç", "fast"),
    ("kurumda kaç kişi kayıtlı", "fast"),
    ("kurum özeti ver", "fast"),

    # ── Öğretmen Bilgi ──
    ("vedat hoca nasıl", "fast"),
    ("emin hoca etüt durumu", "fast"),
    ("orhan hocanın performansı", "fast"),
    ("hocaların etüt yogunluklarını kıyasla", "fast"),
    ("öğretmenleri karşılaştır", "fast"),

    # ── Öğretmen Program Detay ──
    ("emin hoca salı günü", "fast"),
    ("orhan hoca çarşamba programı", "fast"),
    ("vedat hocanın programı", "fast"),

    # ── Öğrenci Akademik ──
    ("ali küçükuysal nasıl", "fast"),
    ("ayşe akademik durumu", "fast"),
    ("mehmet performansı nasıl", "fast"),
    ("ahmet'in sınav sonuçları", "fast"),

    # ── En Başarılı ──
    ("en başarılı öğrenci kim", "fast"),
    ("en yüksek net yapan kim", "fast"),
    ("birinci kim", "fast"),

    # ── Devamsızlık ──
    ("en çok devamsız yapan kim", "fast"),
    ("devamsızlık listesi", "fast"),
    ("devamsızlıkta sıralama", "fast"),

    # ── En Çok Etüt ──
    ("en çok etüt alan öğrenci kim", "fast"),
    ("en fazla etüt yapan", "fast"),
    ("etüt katılım oranı en yüksek kim", "fast"),

    # ── Selamlama ──
    ("merhaba", "fast"),
    ("selam", "fast"),

    # ── İmla Hatalı Admin ──
    ("sali gunu kimler var", "fast"),  # ı→i ü→u
    ("carsamba hocalarin dersi", "fast"),  # ş→s, ı→i
    ("11 sinif ogrencileri", "fast"),  # ı→i, ö→o
    ("kac ogrenci var", "fast"),  # ç→c ö→o
    ("sinif dagilimi", "fast"),  # ı→i
    ("ogretmenleri karsilastir", "fast"),  # ö→o ş→s ı→i
    ("vedat hocanin durumu", "fast"),
    ("ali kucukuysal nasil", "fast"),  # ü→u ı→i
    ("en basarili ogrenci", "fast"),  # ş→s ı→i ö→o
    ("en cok devamsiz", "fast"),  # ç→c
    ("en cok etut alan kim", "fast"),
    ("emin hoca sali gunu", "fast"),  # ı→i ü→u
]

# LLM Router classify testi — cloud'a gitmesi gerekenler
MUST_BE_CLOUD = [
    "11 sınıfta kaç öğrenci var",
    "sınıfları listele",
    "kurumdaki sınıfları göster",
    "en çok devamsız yapan kim",
    "öğretmenlerin etüt yoğunluğu",
    "Ali'nin son deneme sonuçları",
    "denemede kaç net yaptım",
    "rehberlik görüşmelerim",
    "haftalık etüt planı",
    "devamsızlık sıralaması",
    "sınav analizi yap",
    "hangi konularda zayıfım",
    "son deneme sonuçları",
    "ders programım",
    "ogrenci listesi ver",
    "öğrenci sayısı kaç",
    "sınıf dağılımı",
    "kaç kişi kurumda var",
    "etüt istatistikleri",
    "öğretmen performansı",
]

# Ollama'da kalması gerekenler (veri gerektirmiyor)
MUST_STAY_LOCAL = [
    "merhaba",
    "nasılsın",
    "kaldırma kuvveti nedir",
    "logaritma nasıl hesaplanır",
    "türev ne işe yarar",
    "teşekkürler",
    "sağol",
    "iyi günler",
    "canım sıkılıyor",
    "motivasyonum düşük",
]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def test_fast_response_coverage():
    """Fast response pattern coverage testi."""
    from fast_responses import try_fast_response, OGRENCI_PATTERNS, OGRETMEN_PATTERNS, ADMIN_PATTERNS

    print("\n" + "="*80)
    print("FAST RESPONSE PARAPHRASE COVERAGE TEST")
    print("="*80)

    total = 0
    passed = 0
    failed_items = []

    # ── Öğrenci Testleri ──
    print("\n--- OGRENCI TESTLERI ---")
    for msg, expected in OGRENCI_TESTS:
        total += 1
        if expected == "local_ok":
            # Bu Ollama'ya gitmeli — fast_response None donmeli
            result = await try_fast_response(msg, "905001234567", "ogrenci", soz_no=200, name="Test Ogrenci")
            if result is None:
                passed += 1
                print(f"  ✅ [LOCAL_OK] \"{msg}\" → None (Ollama'ya gidecek)")
            else:
                # fast_response yakaladiysa daha iyi
                passed += 1
                print(f"  ✅ [BONUS]    \"{msg}\" → fast_response yakaladi (daha iyi!)")
        elif expected == "fast":
            result = await try_fast_response(msg, "905001234567", "ogrenci", soz_no=200, name="Test Ogrenci")
            if result is not None:
                passed += 1
                # Gorsel kalite kontrolu
                has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF]', result))
                has_bold = '*' in result
                has_newline = '\n' in result
                quality = "🟢" if (has_emoji and has_bold and has_newline) else "🟡" if has_bold else "🔴"
                preview = result[:60].replace('\n', ' ')
                print(f"  ✅ [FAST] {quality} \"{msg}\" → \"{preview}...\"")
            else:
                # Fast response yakalamadı — classify_complexity kontrol et
                complexity = classify_complexity(msg)
                if complexity == "cloud":
                    passed += 1  # Claude yakalayacak, tehlikeli degil
                    print(f"  🟡 [CLOUD]    \"{msg}\" → fast miss ama cloud routing OK")
                else:
                    failed_items.append(("ogrenci", msg, "fast", complexity))
                    print(f"  ❌ [MISS]     \"{msg}\" → fast:None, router:{complexity} — OLLAMA'YA DUSECEK!")

    # ── Öğretmen Testleri ──
    print("\n--- OGRETMEN TESTLERI ---")
    for msg, expected in OGRETMEN_TESTS:
        total += 1
        if expected == "local_ok":
            result = await try_fast_response(msg, "905009876543", "ogretmen", staff_name="Test Ogretmen")
            if result is None:
                passed += 1
                print(f"  ✅ [LOCAL_OK] \"{msg}\" → None (Ollama)")
            else:
                passed += 1
                print(f"  ✅ [BONUS]    \"{msg}\" → fast_response")
        elif expected == "fast":
            result = await try_fast_response(msg, "905009876543", "ogretmen", staff_name="Test Ogretmen")
            if result is not None:
                passed += 1
                quality = "🟢" if '*' in result and '\n' in result else "🟡"
                preview = result[:60].replace('\n', ' ')
                print(f"  ✅ [FAST] {quality} \"{msg}\" → \"{preview}...\"")
            else:
                complexity = classify_complexity(msg)
                if complexity == "cloud":
                    passed += 1
                    print(f"  🟡 [CLOUD]    \"{msg}\" → cloud routing OK")
                else:
                    failed_items.append(("ogretmen", msg, "fast", complexity))
                    print(f"  ❌ [MISS]     \"{msg}\" → OLLAMA'YA DUSECEK!")

    # ── Admin Testleri ──
    print("\n--- ADMIN TESTLERI ---")
    for msg, expected in ADMIN_TESTS:
        total += 1
        if expected == "fast":
            result = await try_fast_response(msg, "905051256802", "admin", name="Zeki Göksal")
            if result is not None:
                passed += 1
                quality = "🟢" if '*' in result and '\n' in result else "🟡"
                preview = result[:60].replace('\n', ' ')
                print(f"  ✅ [FAST] {quality} \"{msg}\" → \"{preview}...\"")
            else:
                complexity = classify_complexity(msg)
                if complexity == "cloud":
                    passed += 1
                    print(f"  🟡 [CLOUD]    \"{msg}\" → cloud routing OK")
                else:
                    failed_items.append(("admin", msg, "fast", complexity))
                    print(f"  ❌ [MISS]     \"{msg}\" → OLLAMA'YA DUSECEK!")

    print(f"\n{'='*80}")
    print(f"SONUC: {passed}/{total} basarili ({passed/total*100:.0f}%)")

    if failed_items:
        print(f"\n{'='*80}")
        print(f"TEHLIKELI KACIRILMALAR ({len(failed_items)} adet):")
        print(f"Bu sorular Ollama'ya dusecek ve halusinasyon riski var!")
        print(f"{'='*80}")
        for role, msg, expected, got in failed_items:
            print(f"  [{role:10s}] \"{msg}\" → beklenen:{expected}, gercek router:{got}")

    return failed_items


def test_llm_router_classification():
    """LLM Router'in veri sorularini dogru siniflandirip siniflandirmadigini test et."""
    print("\n" + "="*80)
    print("LLM ROUTER CLASSIFICATION TEST")
    print("="*80)

    failed = []

    print("\n--- CLOUD'A GITMESI GEREKENLER ---")
    for msg in MUST_BE_CLOUD:
        result = classify_complexity(msg)
        if result in ("cloud", "auto"):
            print(f"  ✅ \"{msg}\" → {result}")
        else:
            print(f"  ❌ \"{msg}\" → {result} (CLOUD olmali!)")
            failed.append(("cloud", msg, result))

    print("\n--- LOCAL'DE KALMASI GEREKENLER ---")
    for msg in MUST_STAY_LOCAL:
        result = classify_complexity(msg)
        if result == "local":
            print(f"  ✅ \"{msg}\" → local")
        else:
            print(f"  🟡 \"{msg}\" → {result} (local beklendi, maliyet artacak)")

    if failed:
        print(f"\n{'='*80}")
        print(f"TEHLIKELI ROUTER HATALARI ({len(failed)}):")
        print(f"Bu sorular local'de kalacak ve Ollama halusinasyon yapacak!")
        print(f"{'='*80}")
        for expected, msg, got in failed:
            print(f"  \"{msg}\" → {got} (olmasi gereken: {expected})")

    return failed


async def main():
    print("FermatAI Paraphrase Coverage & Quality Test")
    print("=" * 80)

    # 1. LLM Router testi
    router_fails = test_llm_router_classification()

    # 2. Fast response coverage testi
    fast_fails = await test_fast_response_coverage()

    # 3. Ozet
    print("\n" + "="*80)
    print("GENEL OZET")
    print("="*80)
    total_fails = len(router_fails) + len(fast_fails)
    if total_fails == 0:
        print("✅ TUM TESTLER GECTI! Ollama'ya tehlikeli soru dusmuyor.")
    else:
        print(f"⚠️ {total_fails} TEHLIKELI KACIRILMA VAR!")
        print("Bu sorular Ollama'ya duserse halusinasyon yapilabilir.")
        print("Cozum: fast_response'a yeni pattern ekle VEYA classify_complexity'ye keyword ekle.")


if __name__ == "__main__":
    asyncio.run(main())
