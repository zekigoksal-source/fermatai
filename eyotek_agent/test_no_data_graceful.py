"""
FermatAI No-Data Graceful Response Test
=======================================
Veri yokken sistem nasil davranir? Hata mesaji mi, yoksa
stratejik pedagojik yaklasim mi?

KURALLAR:
  - ASLA teknik hata mesaji gostermemeli
  - ASLA "bulunamadi", "hata olustu", "None", "null" yazmamalı
  - ASLA bos veya anlamsiz cevap donmemeli
  - Veri yoksa: bağlamı açıklayıp alternatif öner veya karşı soru sor
  - Profesyonel, sıcak, eğitimci tonu korunmalı
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

# ═══════════════════════════════════════════════════════════════════
# YASAK KELIMELER — bunlari goren ogrenci/veli soguyor
# ═══════════════════════════════════════════════════════════════════

FORBIDDEN_WORDS = [
    # Teknik hatalar
    "error", "exception", "traceback", "null", "none", "undefined",
    "typeerror", "keyerror", "attributeerror", "indexerror",
    "connection", "timeout", "database", "postgresql", "asyncpg",
    "sql", "query", "table", "column", "fetch", "insert",
    # Kotu kullanici deneyimi
    "bulunamadi", "bulunamadı",  # tek basina - context'e gore kontrol
    "hata olustu", "hata oluştu", "hata meydana",
    "sistem hatasi", "sistem hatası",
    "islem basarisiz", "işlem başarısız",
    "bos", "boş döndü", "boş geldi",
    "kayit yok", "kayıt yok",
    "veri yok", "veri bulunamadı",
    "mevcut degil", "mevcut değil",
    "tanimsiz", "tanımsız",
    "gecersiz", "geçersiz",
    "bilinmiyor", "bilinmeyen hata",
    # LLM/teknik sızıntı
    "anthropic", "claude", "ollama", "token", "prompt",
    "tool_use", "textblock", "toolresult",
    "veritabani", "veritabanı", "database",
    "fast_response", "fast response",
]

# İzin verilen "bulunamadı" kullanımları (context'li)
ALLOWED_BULUNAMADI = [
    "ders programi bulunamadi",  # ders programı gerçekten yoksa OK
    "eslesen ogrenci bulunamadi",  # arama sonucu bos
    "ile eslesen",  # arama bağlamı
]


def check_forbidden(response: str) -> list:
    """Yasak kelime kontrolu. Bulunanları listele."""
    found = []
    resp_lower = response.lower()
    for word in FORBIDDEN_WORDS:
        if word in resp_lower:
            # "bulunamadı" özel kontrol
            if "buluna" in word:
                if any(allowed in resp_lower for allowed in ALLOWED_BULUNAMADI):
                    continue
            found.append(word)
    return found


def check_quality(response: str) -> str:
    """A/B/C/D/F gorsel kalite."""
    if not response or len(response.strip()) < 10:
        return "F"
    has_emoji = bool(re.search(r'[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U00002600-\U000026FF]', response))
    has_bold = '*' in response
    has_newline = '\n' in response
    has_italic = '_' in response
    score = 0
    if has_emoji: score += 2
    if has_bold: score += 2
    if has_newline: score += 2
    if has_italic: score += 1
    if len(response) >= 80: score += 1
    return "A" if score >= 6 else "B" if score >= 4 else "C" if score >= 2 else "D"


def is_pedagogical(response: str) -> bool:
    """Pedagojik/stratejik cevap mi? (soru soruyor, alternatif oneriyor, yonlendiriyor)"""
    indicators = [
        r"\?",  # soru isareti — karsi soru soruyor
        r"(yazabilirsin|sorabilirsin|istersen|dene|bakalim|birlikte)",  # yonlendirme
        r"(oner|öneri|tavsiye|plan|hedef|odaklan)",  # alternatif onerme
        r"(yardimci|yardımcı|destek|rehber)",  # destek tonu
        r"(henuz|henüz|yakinda|yakında|sonra|devam)",  # zaman bağlamı
        r"(katildikca|katıldıkça|geldikce|geldikçe|oldukca|oldukça)",  # gelecek vaadi
    ]
    for pat in indicators:
        if re.search(pat, response.lower()):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
# TEST SENARYOLARI — Veri yok ama cevap stratejik olmali
# ═══════════════════════════════════════════════════════════════════

# soz_no=9999 → var olmayan ogrenci
# soz_no=181 → Zeynep Uz, sinav verisi yok
# soz_no=243 → Berrak, sinif 7, muhtemelen bircok veri eksik

NO_DATA_TESTS = [
    # ── Sinav verisi olmayan ogrenci ──
    {
        "msg": "son denemem nasil",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Sinav verisi olmayan ogrenci son deneme soruyor",
        "expect": "pedagogical",  # hata degil, yonlendirici cevap
    },
    {
        "msg": "son 3 denememi kiyasla",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Sinav verisi olmayan ogrenci kiyaslama istiyor",
        "expect": "pedagogical",
    },
    {
        "msg": "zayif konularim neler",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Konu verisi olmayan ogrenci zayif konu soruyor",
        "expect": "pedagogical",
    },
    {
        "msg": "guclu konularim neler",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Konu verisi olmayan ogrenci guclu konu soruyor",
        "expect": "pedagogical",
    },
    {
        "msg": "devamsizligim kac saat",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Devamsizlik verisi olmayan ogrenci",
        "expect": "pedagogical",
    },
    {
        "msg": "hedefim ne olmali",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Analiz verisi olmayan ogrenci hedef soruyor",
        "expect": "pedagogical",
    },
    {
        "msg": "calisma plani yap",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Verisi az olan ogrenci calisma plani istiyor",
        "expect": "pedagogical",
    },
    {
        "msg": "rehberlik gorusmelerim",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Rehberlik notu olmayan ogrenci",
        "expect": "pedagogical",
    },
    {
        "msg": "etutlerime bakabilir misin",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Etut bilgisi sınırlı ogrenci",
        "expect": "pedagogical",
    },

    # ── Sinif bilgisi olmayan ogrenci ──
    {
        "msg": "ders programim ne",
        "role": "ogrenci", "soz_no": 243, "name": "Berrak Talya Ulcay",
        "desc": "Sinif bilgisi eksik ogrenci ders programi soruyor",
        "expect": "pedagogical",
    },

    # ── Admin: var olmayan ogrenci ──
    {
        "msg": "ahmet yildirimoglu nasil",
        "role": "admin", "soz_no": None, "name": "Zeki Goksal",
        "desc": "Admin olmayan ogrenciyi soruyor",
        "expect": "no_match",  # eslesmeme — ama hata mesaji degil
    },
    {
        "msg": "xyz sinifi listele",
        "role": "admin", "soz_no": None, "name": "Zeki Goksal",
        "desc": "Admin olmayan sinifi soruyor",
        "expect": "no_match",
    },

    # ── Admin: yarin/gelecek tarih ──
    {
        "msg": "pazar gunu programi",
        "role": "admin", "soz_no": None, "name": "Zeki Goksal",
        "desc": "Admin pazar gunu programi soruyor (ders yok)",
        "expect": "informative",
    },

    # ── Ogretmen: bos gun ──
    {
        "msg": "bugunki derslerim ne",
        "role": "ogretmen", "soz_no": None, "name": "",
        "staff_name": "Yokolan Hoca",
        "desc": "Ogretmen timetable'da olmayan kisinin dersleri",
        "expect": "pedagogical",
    },

    # ── Ogrenci: belirsiz / anlamsiz mesajlar ──
    {
        "msg": "asdfghjkl",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Anlamsiz klavye basisi",
        "expect": "clarify",  # ne demek istedigini sor
    },
    {
        "msg": ".",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Sadece nokta",
        "expect": "clarify",
    },
    {
        "msg": "hmm",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Sadece hmm — dusunuyor",
        "expect": "clarify",
    },
    {
        "msg": "tamam",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Tamam — ne icin tamam?",
        "expect": "clarify",
    },
    {
        "msg": "ok",
        "role": "ogrenci", "soz_no": 181, "name": "Zeynep Uz",
        "desc": "Sadece ok",
        "expect": "clarify",
    },

    # ── Guest: ic veri talep ediyor ──
    {
        "msg": "ogrenci listesi ver",
        "role": "guest", "soz_no": None, "name": "",
        "desc": "Guest ic veri istiyor — engellenmeli",
        "expect": "blocked",
    },
    {
        "msg": "ogretmenlerin isimlerini soyler misin",
        "role": "guest", "soz_no": None, "name": "",
        "desc": "Guest personel bilgisi istiyor",
        "expect": "blocked",
    },
]


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════

async def run_tests():
    from fast_responses import try_fast_response
    from llm_router import classify_complexity

    print("=" * 80)
    print("  NO-DATA GRACEFUL RESPONSE TEST")
    print("  Veri yokken hata mesaji yerine stratejik cevap kontrolu")
    print("=" * 80)

    total = 0
    passed = 0
    issues = []

    for t in NO_DATA_TESTS:
        total += 1
        msg = t["msg"]
        role = t["role"]
        soz_no = t.get("soz_no")
        name = t.get("name", "")
        staff_name = t.get("staff_name", "")
        desc = t["desc"]
        expect = t["expect"]
        phone = "905001234567"

        result = await try_fast_response(msg, phone, role,
                                          soz_no=soz_no, name=name, staff_name=staff_name)
        complexity = classify_complexity(msg)

        # Analiz
        if result is not None:
            # Fast response cevap verdi — kalite kontrol
            forbidden = check_forbidden(result)
            quality = check_quality(result)
            ped = is_pedagogical(result)
            preview = result[:100].replace('\n', ' ')

            if forbidden:
                issues.append(("YASAK_KELIME", desc, forbidden, result[:200]))
                print(f"  [!!] YASAK   {desc}")
                print(f"       Bulunan: {', '.join(forbidden)}")
                print(f"       Cevap: \"{preview}...\"")
            elif quality in ("D", "F"):
                issues.append(("KALITE_DUSUK", desc, quality, result[:200]))
                print(f"  [!!] KAL[{quality}]  {desc}")
                print(f"       Cevap: \"{preview}...\"")
            else:
                passed += 1
                ped_icon = "PED" if ped else "   "
                print(f"  [OK] [{quality}]{ped_icon} {desc}")
                print(f"       \"{preview}...\"")
        else:
            # Fast response yakalamadi — Claude/Ollama'ya gidecek
            if expect in ("clarify", "blocked"):
                # Bu mesajlar icin fast_response yakalamamasi beklenir
                # Ama Ollama'ya duserse tehlike var
                if complexity == "local":
                    issues.append(("OLLAMA_RISK", desc, complexity, "None"))
                    print(f"  [!!] OLLAMA  {desc}")
                    print(f"       Fast:None, router:local — Ollama sacma cevap verebilir!")
                else:
                    passed += 1
                    print(f"  [OK] CLOUD  {desc}")
                    print(f"       → Claude yanitlayacak ({complexity})")
            elif expect == "no_match":
                passed += 1
                print(f"  [OK] PASS   {desc}")
                print(f"       → None (ogrenci bulunamadi ama hata yok, Claude devam edecek)")
            else:
                # Veri sorgusu ama fast_response yakalamadi
                if complexity in ("cloud", "auto"):
                    passed += 1
                    print(f"  [OK] CLOUD  {desc}")
                    print(f"       → Claude yanitlayacak ({complexity})")
                else:
                    issues.append(("OLLAMA_RISK", desc, complexity, "None"))
                    print(f"  [!!] OLLAMA  {desc}")
                    print(f"       Fast:None, router:{complexity} — VERI YOK + OLLAMA = HALUSINASYON!")

    # OZET
    print(f"\n{'='*80}")
    print(f"SONUC: {passed}/{total} basarili ({passed/total*100:.0f}%)")

    if issues:
        print(f"\n{'='*80}")
        print(f"SORUNLAR ({len(issues)}):")
        print(f"{'='*80}")
        for typ, desc, detail, preview in issues:
            if typ == "YASAK_KELIME":
                print(f"  [YASAK]  {desc}")
                print(f"           Kelimeler: {detail}")
                print(f"           Cevap: \"{preview[:120]}...\"")
            elif typ == "KALITE_DUSUK":
                print(f"  [KALITE] {desc} — Grade: {detail}")
                print(f"           Cevap: \"{preview[:120]}...\"")
            elif typ == "OLLAMA_RISK":
                print(f"  [OLLAMA] {desc}")
                print(f"           → Ollama'ya dusecek, veri olmadan halusinasyon riski!")
    else:
        print(f"\n  [KUSURSUZ] Hicbir yasak kelime yok, gorsel kalite yuksek!")

    return issues


if __name__ == "__main__":
    asyncio.run(run_tests())
