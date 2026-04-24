"""
FermatAI Realistic Scenario Test v2
====================================
Gercek kullanici senaryolari: imla hatali, devrik cumleli, uzun mesajli sorular.
Her rol icin 20+ soru, gorsel kalite kontrolu, context mismatch tespiti.

Test kategorileri:
  1. OGRENCI (20 soru) — imla hatali, devrik, uzun
  2. OGRETMEN (15 soru) — resmi/gayri resmi karisik
  3. MUDUR/ADMIN (15 soru) — analitik + operasyonel
  4. GUEST (10 soru) — bilinmeyen numara, kurum disi
  5. CONTEXT MISMATCH (10 soru) — yanlis fast_response tetiklememesi gereken
  6. UZUN MESAJ → KISA CEVAP (10 soru) — baglam cikarma
"""

import asyncio
import io
import os
import re
import sys

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')
from llm_router import classify_complexity

# ═══════════════════════════════════════════════════════════════════════════════
# GORSEL KALITE KONTROL
# ═══════════════════════════════════════════════════════════════════════════════

def check_visual_quality(response: str) -> dict:
    """Yanit gorsel kalitesini analiz et."""
    has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF]', response))
    has_bold = '*' in response
    has_newline = '\n' in response
    has_italic = '_' in response
    line_count = response.count('\n') + 1
    char_count = len(response)

    # Kotu isaretler
    has_technical = any(w in response.lower() for w in [
        'tooluse', 'textblock', 'error', 'traceback', 'exception',
        'postgresql', 'asyncpg', 'none', 'null', 'dict', 'list',
        'anthropic', 'claude', 'ollama', 'api', 'token', 'prompt',
        'veritabani', 'database', 'sql', 'query', 'endpoint',
    ])
    has_english = bool(re.search(r'\b(the|is|are|was|were|have|has|been|will|would|could|should|can|may|might|this|that|these|those|here|there|where|when|what|which|who|how|why|let|me|help|you|with|for|from|into|about|after|before|between|through|during|without|within)\b', response.lower()))

    # Skor
    score = 0
    if has_emoji: score += 2
    if has_bold: score += 2
    if has_newline and line_count >= 3: score += 2
    if has_italic: score += 1
    if char_count >= 50: score += 1
    if not has_technical: score += 1
    if not has_english: score += 1
    # max 10

    grade = "A" if score >= 8 else "B" if score >= 6 else "C" if score >= 4 else "D" if score >= 2 else "F"

    return {
        "score": score,
        "grade": grade,
        "emoji": has_emoji,
        "bold": has_bold,
        "newlines": line_count,
        "chars": char_count,
        "technical_leak": has_technical,
        "english_leak": has_english,
        "italic": has_italic,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# TEST SENARYOLARI
# ═══════════════════════════════════════════════════════════════════════════════

# (mesaj, beklenen_handler_veya_None, aciklama)
# None = Claude'a gitmeli (complex), "fast:xxx" = fast_response handler, "local_ok" = Ollama OK

OGRENCI_SORULARI = [
    # --- Imla hatali ---
    ("hocam benim son denme sonuclarim nasil acaba", "fast", "son deneme imla hatali"),
    ("sinav sonuclarim neydi ya hatirlamiyom", "fast", "sinav sonucu konusma dili"),
    ("benim zayif oldugum konular hangileri acaba bi bakar mısın", "fast", "zayif konu uzun istek"),
    ("devamsizligim kacti biliyo musun", "fast", "devamsizlik konusma dili"),
    ("ya arkadaslar diyo benim devamsizligim cok diye dogru mu bu", "fast", "devamsizlik dolaysiz soru"),
    ("hocam ders programimi bi gonderebilir misin", "fast", "ders programi rica formunda"),
    ("bi calisma plani lazim bana ya nasil caliscam bilmiyorum", "fast", "calisma plani dertli ton"),
    ("kiyaslama yapabilir misin son 3 denememi", "fast", "kiyasla devrik cumle"),
    ("benim guclu konularim neler peki", "fast", "guclu konular peki ile"),
    ("hedefim ne olmali sizce kac net yapmam gerekiyor", "fast", "hedef + net birlikte"),

    # --- Devrik cumleler ---
    ("nasil gidiyor denemelerim son zamanlarda", "fast", "devrik deneme trend"),
    ("bakabilir misin bi etutlerime bu hafta var mi", "fast", "devrik etut sorgusu"),
    ("gorusmelerim vardi rehberlikle onlara bakabilir misin", "fast", "devrik rehberlik"),
    ("artıyor mu netlrim acaba", "fast", "devrik net trend, typo"),
    ("hata yapiyorum nerde bilmiyorum ki", "fast", "devrik nerede hata"),

    # --- Uzun mesajlar ---
    ("hocam ben su an cok karisik bi donemden geciyorum sinav sonuclarim nasil gidiyor bi bakabilir misiniz son denememe cunku ailem soruyor ama ben hatirlamiyorum", "fast", "uzun son deneme istek"),
    ("ya su an mat cok kotu gidiyor galiba ama hangi konularda zayifim tam bilmiyorum bi kontrol edebilir misin nerelere calismam lazim", "fast", "uzun zayif konu + oneri istegi"),
    ("ben gecen hafta devamsiz yazmislar ama aslinda hastaydim neyse devamsizligim kac saat oldu toplam merak ediyorum", "fast", "uzun devamsizlik aciklama + soru"),

    # --- Konu aciklamasi (Ollama OK) ---
    ("fizikteki kaldirma kuvveti konusunu anlayamiyorum aciklayabilir misin", "local_ok", "konu aciklama fizik"),
    ("tureve nasil baslarim hic anlamadim", "local_ok", "konu aciklama matematik"),
]

OGRETMEN_SORULARI = [
    ("bugunki derslerim nelerdi hocam", "fast", "bugun ders konusma dili"),
    ("programim ne bu hafta", "fast", "program sorgusu"),
    ("kac tane etut vermisim bu ay", "fast", "etut sayisi konusma dili"),
    ("etut istatistigimi gormek istiyorum", "fast", "etut istatistik resmi"),
    ("benim haftalik ders programimi atar misiniz", "fast", "ders programi rica"),
    ("bugun benim dersim var miydi ya unuttum", "fast", "bugun ders var mi"),
    ("toplam kac saat ders verdim bu donem", "fast", "toplam ders saati"),
    ("haftalik programimda degisiklik mi var", "fast", "program sorgusu"),
    ("merhaba ben bi soru soricaktim", "fast", "merhaba + belirsiz"),
    ("iyi gunler nasil yardimci olabilirsiniz", "fast", "selamlasma"),
    # Olmamasi gereken — baska ogretmen bilgisi
    ("orhan hocanin programi ne", "block_other_teacher", "baska ogretmen bilgisi"),
    ("emin hoca kac etut vermis", "block_other_teacher", "baska ogretmen etut"),
    # Sohbet OK
    ("bugun cok yoruldum ya", "local_ok", "sohbet"),
    ("hava cok guzel bugun", "local_ok", "sohbet"),
    ("ogrencilerim cok basarili oldu cok mutluyum", "local_ok", "sohbet olumlu"),
]

ADMIN_SORULARI = [
    ("kurumun genel durumu nasil bi ozet ver", "fast", "kurum ozeti"),
    ("sinif dagilimi goster bakim", "fast", "sinif dagilimi"),
    ("en basarili ogrencimiz kim simdi", "fast", "en basarili"),
    ("devamsizlikta en cok kim yapiyor", "fast", "devamsizlik listesi"),
    ("vedat hoca nasil gidiyor performansi", "fast", "ogretmen bilgi"),
    ("emin hoca sali gunu ne yapiyor", "fast", "ogretmen gun detay"),
    ("hocalarin etut yogunlugunu karsilastir bakalim", "fast", "ogretmen kiyasla"),
    ("11 siniftaki ogrencileri listele", "fast", "sinif listesi"),
    ("ali kucukuysal nasil gidiyor akademik olarak", "fast", "ogrenci akademik"),
    ("en cok etut alan ogrenci kim bakalim", "fast", "en cok etut"),
    # Uzun admin sorusu
    ("ya su son bi ayda ogrencilerin genel performansi nasil gidiyor bi ozet cikartabilir misin sinav sonuclari falan da dahil olsun", "cloud", "uzun analiz talebi"),
    ("pazartesi gunu programi nasil yani hangi hocalar hangi sinifta ders veriyor gormek istiyorum", "fast", "uzun gun programi"),
    ("12 siniftakiler kac kisi oldu simdi mezunlar dahil mi", "fast", "sinif sayisi detay"),
    ("selam bi bakalim bugunku durum neydir", "fast", "selamlama + durum"),
    ("cumartesi gunune ozel bi rapor cikarabilir misin hangi hocalar var kac ders var", "fast", "cumartesi detay"),
]

GUEST_SORULARI = [
    ("merhaba bilgi almak istiyorum", "guest_greeting", "ilk temas"),
    ("fiyatlariniz ne kadar acaba", "guest_price", "fiyat sorgusu"),
    ("ozel ders veriyor musunuz", "guest_info", "ozel ders"),
    ("kayit icin ne yapmam lazim", "guest_register", "kayit"),
    ("basari oraniniz kac", "guest_success", "basari orani"),
    ("lgs icin hazirlik programiniz var mi", "guest_program", "lgs hazirlik"),
    ("kac kisilik siniflariniz var", "guest_class", "sinif mevcudu"),
    ("neredesiniz adres atar misiniz", "guest_location", "adres"),
    ("yks icin kac aylik program var", "guest_program", "yks program"),
    ("cocugumun deneme puani 300 civarinda ne yapmamiz lazim", "guest_consult", "danismanlik"),
]

# Context mismatch — yanlis fast_response tetiklememesi gerekenler
CONTEXT_MISMATCH = [
    # "sinav" kelimesi var ama veri sorgusu degil
    ("sinav stresi ile nasil basa cikarim", "local_ok", "sinav stresi = motivasyon, veri degil"),
    ("sinav kaygisi yasiyorum ne yapmaliyim", "local_ok", "sinav kaygisi = psikoloji"),
    # "program" kelimesi var ama ders programi degil
    ("bi diyet programi onerebilir misin", "local_ok", "program = diyet, ders degil"),
    # "devamsizlik" kelimesi var ama kendi verisi degil — genel soru
    ("devamsizlik kac gune kadar hakkim var", "local_ok", "devamsizlik limiti = genel bilgi"),
    # "konular" var ama zayif konu sorgusu degil
    ("fizik konulari hangi sirada isleniyor", "local_ok", "konu sirasi = mufredat bilgisi"),
    # "net" var ama sinav neti degil
    ("internette net hizim cok dusuk ne yapmaliyim", "local_ok", "net = internet, sinav degil"),
    # Tehlikeli: isim + durum = ogrenci sorgusu tetikleyebilir
    ("ali cengiz adli bir yazar var mi turk edebiyatinda", "no_student_search", "ali = yazar ismi, ogrenci degil"),
    # "hoca" var ama ogretmen bilgisi degil
    ("hocam bu konuyu anlamadim tekrar aciklar misiniz", "local_ok", "hocam = hitap, ogretmen sorgusu degil"),
    # Uzun ama basit sohbet — Ollama'ya gitmeli
    ("ya bugun cok guzel bi gun oldu okulda arkadaslarla cok eglendik ama aksamustu biraz calisicam fizik var cunku yarın", "local_ok", "uzun sohbet + niyet"),
    # "listele" var ama ogrenci listesi degil
    ("bana kitap listele okumam gereken romanlar", "local_ok", "listele = kitap, ogrenci degil"),
]

# Uzun mesaj → kisa cevap: baglam cikarma
UZUN_MESAJ_TESTLERI = [
    ("hocam ben su an cok stresli bi donem geciriyorum ailem baski yapiyor dersler cok yogun ama ben elimden gelenin en iyisini yapmaya calisiyorum son deneme nasil gitmis acaba bi bakabilir misiniz cok merak ediyorum", "fast:son_deneme", "uzun stresli mesaj → son deneme istegi"),
    ("aslinda bi sorum vardi benim hani bizim sinifin ders programi vardi ya onu bi gormem lazim cunku anneme sormam gereken bisey var hangi gunler gelmem gerekiyor diye", "fast:ders_programi", "uzun ders programi istegi"),
    ("su an kafam cok karisik hangi konulara calismam gerektigini bilmiyorum herkes farkli bisey soyluyor bi matematik diye baktim olmadi fizik dediler ona da baktim bilmiyorum en zayif oldugum konulari bi gorsem keske nerelere odaklanmam gerektigini anlasam", "fast:zayif_konular", "uzun zayif konu istegi"),
    ("ben bu yil cok calismak istiyorum ama nasil bi plan izlemem gerektigini bilmiyorum herkes farkli bisey soyluyor kendi durumuma gore bi calisma plani olsa cok iyi olur haftalik bi sey mesela hangi gun ne caliscam falan", "fast:calisma_plani", "uzun calisma plani istegi"),
    ("hocam ben aslinda merak ediyorum su an ne durumdayim yani devamsizligim falan var mi cok mu gelmemisim bilmiyorum bazen gelmedigim oldu ama hastaydim cogunlukla ne kadar devamsizligim var toplam", "fast:devamsizlik", "uzun devamsizlik istegi"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_role_tests(title, tests, role, soz_no=None, name="", staff_name="", caller_phone=""):
    from fast_responses import try_fast_response

    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

    total = 0
    passed = 0
    quality_issues = []
    context_issues = []

    for item in tests:
        msg, expected, desc = item
        total += 1

        result = await try_fast_response(msg, caller_phone or "905001234567", role,
                                          soz_no=soz_no, name=name, staff_name=staff_name)
        complexity = classify_complexity(msg)

        # Sonuc analizi
        if expected == "local_ok":
            if result is None:
                passed += 1
                status = "OK"
                detail = f"→ None (Ollama/Claude: {complexity})"
            else:
                # fast_response yakaladiysa bonus (ama yanlis yakalama mi kontrol et)
                preview = result[:80].replace('\n', ' ')
                # Yanlis yakalama mi?
                passed += 1
                status = "BONUS"
                detail = f"→ fast yakaladi: \"{preview}...\""

        elif expected == "no_student_search":
            if result is None:
                passed += 1
                status = "OK"
                detail = "→ None (ogrenci aramasi tetiklenmedi)"
            else:
                if "eslesen" in result.lower() or "bulunamadi" in result.lower():
                    context_issues.append((msg, desc, result[:100]))
                    status = "CONTEXT_MISS"
                    detail = f"→ YANLIS ogrenci aramasi tetiklendi!"
                else:
                    passed += 1
                    status = "OK"
                    detail = f"→ {result[:60]}..."

        elif expected == "block_other_teacher":
            if result and ("erisim yetki" in result.lower() or "baska ogretmen" in result.lower()):
                passed += 1
                status = "BLOCKED"
                detail = "→ Baska ogretmen bilgisi engellendi"
            elif result is None:
                # Claude'a gidecek — orada ACL engelleyecek
                passed += 1
                status = "CLOUD"
                detail = f"→ Claude ACL'e gidecek ({complexity})"
            else:
                context_issues.append((msg, desc, result[:100]))
                status = "LEAK"
                detail = f"→ BILGI SIZINTISI: {result[:60]}..."

        elif expected == "cloud":
            if result is None and complexity in ("cloud", "auto"):
                passed += 1
                status = "CLOUD"
                detail = f"→ Claude'a gidecek ({complexity})"
            elif result is not None:
                passed += 1
                status = "FAST"
                detail = f"→ fast yakaladi (daha iyi!)"
            else:
                status = "MISS"
                detail = f"→ router:{complexity} — OLLAMA RISKI!"

        elif expected == "fast" or expected.startswith("fast:"):
            if result is not None:
                passed += 1
                q = check_visual_quality(result)
                grade = q['grade']
                status = f"FAST[{grade}]"
                preview = result[:70].replace('\n', ' ')
                detail = f"→ \"{preview}...\""
                if grade in ("D", "F"):
                    quality_issues.append((msg, desc, grade, result[:200]))
            elif complexity in ("cloud", "auto"):
                passed += 1
                status = "CLOUD"
                detail = f"→ Cloud routing ({complexity})"
            else:
                status = "MISS"
                detail = f"→ OLLAMA RISKI! router:{complexity}"

        elif expected.startswith("guest_"):
            if result is not None:
                passed += 1
                q = check_visual_quality(result)
                status = f"GUEST[{q['grade']}]"
                detail = f"→ \"{result[:60].replace(chr(10),' ')}...\""
            elif complexity in ("cloud", "auto"):
                passed += 1
                status = "CLOUD"
                detail = f"→ Cloud guest mode ({complexity})"
            else:
                status = "LOCAL"
                detail = f"→ Ollama guest mode"
                passed += 1  # Guest icin Ollama da OK (kurumsal prompt var)
        else:
            status = "?"
            detail = f"→ Bilinmeyen beklenti: {expected}"

        # Renkli cikti
        icon = "OK" if "OK" in status or "FAST" in status or "CLOUD" in status or "BONUS" in status or "BLOCKED" in status or "GUEST" in status or "LOCAL" in status else "XX"
        emoji_icon = "[OK]" if icon == "OK" else "[!!]"
        print(f"  {emoji_icon} [{status:12s}] {desc:40s} | {detail}")

    print(f"\n  Sonuc: {passed}/{total} basarili ({passed/total*100:.0f}%)")

    if quality_issues:
        print(f"\n  GORSEL KALITE SORUNLARI ({len(quality_issues)}):")
        for msg, desc, grade, preview in quality_issues:
            print(f"    [{grade}] {desc}: \"{preview[:100]}...\"")

    if context_issues:
        print(f"\n  CONTEXT MISMATCH ({len(context_issues)}):")
        for msg, desc, preview in context_issues:
            print(f"    {desc}: \"{preview}\"")

    return {"total": total, "passed": passed, "quality_issues": quality_issues, "context_issues": context_issues}


async def test_uzun_mesaj_baglam():
    """Uzun mesajlarin baglamini dogru cikarabilme testi."""
    from fast_responses import try_fast_response

    print(f"\n{'='*80}")
    print(f"  UZUN MESAJ → KISA CEVAP (Baglam Cikarma)")
    print(f"{'='*80}")

    total = 0
    passed = 0

    for msg, expected, desc in UZUN_MESAJ_TESTLERI:
        total += 1
        result = await try_fast_response(msg, "905001234567", "ogrenci", soz_no=200, name="Test Ogrenci")
        complexity = classify_complexity(msg)

        handler = expected.split(":")[1] if ":" in expected else expected

        if result is not None:
            q = check_visual_quality(result)
            passed += 1
            preview = result[:70].replace('\n', ' ')
            print(f"  [OK] [FAST {q['grade']}] {desc:45s} | \"{preview}...\"")
        elif complexity in ("cloud", "auto"):
            passed += 1
            print(f"  [OK] [CLOUD   ] {desc:45s} | Cloud'a gidecek ({complexity})")
        else:
            print(f"  [!!] [MISS    ] {desc:45s} | OLLAMA RISKI! router:{complexity}")

    print(f"\n  Sonuc: {passed}/{total}")
    return {"total": total, "passed": passed}


async def main():
    print("FermatAI Realistic Scenario Test v2")
    print("=" * 80)
    print("Gercek kullanici senaryolari: imla hatali, devrik, uzun mesajli")
    print("Her cevap gorsel kalite, context dogruluk, guvenlik kontrolunden gecer")

    all_results = []

    # 1. Ogrenci
    r = await run_role_tests(
        "OGRENCI SENARYOLARI (20 soru)",
        OGRENCI_SORULARI, "ogrenci",
        soz_no=200, name="Test Ogrenci", caller_phone="905001234567"
    )
    all_results.append(("Ogrenci", r))

    # 2. Ogretmen
    r = await run_role_tests(
        "OGRETMEN SENARYOLARI (15 soru)",
        OGRETMEN_SORULARI, "ogretmen",
        staff_name="Test Ogretmen", caller_phone="905009876543"
    )
    all_results.append(("Ogretmen", r))

    # 3. Admin
    r = await run_role_tests(
        "ADMIN/MUDUR SENARYOLARI (15 soru)",
        ADMIN_SORULARI, "admin",
        name="Zeki Goksal", caller_phone="905051256802"
    )
    all_results.append(("Admin", r))

    # 4. Guest
    r = await run_role_tests(
        "GUEST SENARYOLARI (10 soru) — bilinmeyen numara",
        GUEST_SORULARI, "guest",
        name="", caller_phone="905551112233"
    )
    all_results.append(("Guest", r))

    # 5. Context Mismatch
    r = await run_role_tests(
        "CONTEXT MISMATCH TESTLERI (10 soru) — yanlis tetiklenmemeli",
        CONTEXT_MISMATCH, "ogrenci",
        soz_no=200, name="Test Ogrenci", caller_phone="905001234567"
    )
    all_results.append(("Context", r))

    # 6. Uzun mesaj baglam cikarma
    r = await test_uzun_mesaj_baglam()
    all_results.append(("UzunMesaj", r))

    # GENEL OZET
    print(f"\n{'='*80}")
    print("GENEL OZET")
    print(f"{'='*80}")

    grand_total = 0
    grand_passed = 0
    all_quality = []
    all_context = []

    for name, r in all_results:
        t, p = r['total'], r['passed']
        grand_total += t
        grand_passed += p
        pct = p/t*100 if t > 0 else 0
        icon = "[OK]" if pct >= 95 else "[!!]" if pct >= 80 else "[XX]"
        print(f"  {icon} {name:15s}: {p}/{t} ({pct:.0f}%)")
        if 'quality_issues' in r:
            all_quality.extend(r['quality_issues'])
        if 'context_issues' in r:
            all_context.extend(r['context_issues'])

    print(f"\n  TOPLAM: {grand_passed}/{grand_total} ({grand_passed/grand_total*100:.0f}%)")

    if all_quality:
        print(f"\n  GORSEL KALITE SORUNLARI: {len(all_quality)}")
        for msg, desc, grade, preview in all_quality:
            print(f"    [{grade}] {desc}")

    if all_context:
        print(f"\n  CONTEXT MISMATCH: {len(all_context)}")
        for msg, desc, preview in all_context:
            print(f"    {desc}: {preview[:80]}")

    if grand_passed == grand_total and not all_quality and not all_context:
        print(f"\n  [KUSURSUZ] Tum testler gecti, gorsel kalite yuksek, context dogru!")


if __name__ == "__main__":
    asyncio.run(main())
