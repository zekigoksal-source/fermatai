"""
Öğrenci Senaryoları — Claude ile önceden hazırlanmış, yerel LLM'in kullanacağı
yapılandırılmış diyalog şablonları ve görsel formatlar.

Her senaryo:
1. Tetikleyici pattern'lar
2. Sorulacak sorular (bağlam toplama)
3. Hazır görsel format (verilerle doldurulur)
4. Claude'a ne zaman eskalasyon gerekir
"""
import re
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# SENARYO 1: ÇALIŞMA PLANI İSTEĞİ
# ═══════════════════════════════════════════════════════════════════

PLAN_QUESTIONS = [
    # Artık generic soru sormuyoruz — Claude build_study_plan_context ile
    # veriye dayalı analiz yapıp kendisi soracak
    None,  # Claude'a yönlendir
]

PLAN_FORMAT = """*{name} — Haftalik Calisma Plani*
_{sinif} | Hedef: {hedef}_

{gunler}

*Oncelikli Konular:*
{konular}

*Gunluk Rutin Onerisi:*
- Sabah (09:00-12:00): Analitik dersler (Mat, Fiz)
- Ogle molasi + 25dk kisa uyku (NASA arastirmasi: %39 performans artisi)
- Ogleden sonra (14:00-18:00): Sozel dersler (Tur, Sosyal)
- Aksam (19:00-21:00): Tekrar + deneme analizi

_"Basari, dogru planlama ve sabirla gelir. Kok sal, meyve zamanla gelecek." — Fermat AI_

Bu plani revize etmemi ister misin? Herhangi bir gunu veya dersi degistirebiliriz.
"""

PLAN_GUN_FORMAT = """
*{gun}:*
  {saat1} — {ders1} ({konu1})
  {saat2} — {ders2} ({konu2})
  {saat3} — Deneme/Tekrar"""


# ═══════════════════════════════════════════════════════════════════
# SENARYO 2: BÖLÜM/ÜNİVERSİTE REHBERLİĞİ
# ═══════════════════════════════════════════════════════════════════

BOLUM_QUESTIONS = [
    "🎓 *Universite Hedef Rehberligi*\n\n"
    "Harika bir hedef! Sana yardimci olabilmem icin:\n\n"
    "1️⃣ Hedef bolumun ne?\n"
    "   _(ornegin Tip, Muhendislik, Hukuk, Psikoloji)_\n\n"
    "2️⃣ Sayisal mi sozel mi esit agirlik mi?\n\n"
    "3️⃣ Hedef universiteler var mi?\n\n"
    "_Bu bilgilerle hedefine ozel yol haritasi olusturacagim!_",
]

BOLUM_FORMAT = """*{name} — Universite Hedef Analizi*

*Hedef:* {bolum}
*Gereken Tahmini Siralama:* {siralama}
*Mevcut Durumun:* {mevcut_net} net (son deneme)

*Hedefe Ulasmak Icin:*
{adimlar}

*Haftalik Odak Alanlari:*
{odak}

_"Her buyuk yolculuk tek bir adimla baslar." Birlikte planlayalim!_
"""


# ═══════════════════════════════════════════════════════════════════
# SENARYO 3: DENEME ANALİZİ YORUMLAMA
# ═══════════════════════════════════════════════════════════════════

DENEME_FORMAT = """*{name} — Deneme Analizi*
_{exam_name} | {exam_date}_

*Toplam:* *{toplam}* net

*Ders Bazli:*
{dersler}

*Degerlendirme:*
{yorum}

*Sonraki Adim:*
{oneri}
"""

DERS_LINE = "  {emoji} {ders}: *{net}* net {trend}"


# ═══════════════════════════════════════════════════════════════════
# SENARYO 4: MOTİVASYON / STRES / DUYGUSAL DESTEK
# ═══════════════════════════════════════════════════════════════════

# Bağlam toplama soruları — Claude'a göndermeden önce durumu netleştir
# Her biri farklı ton ve yaklaşım — random seçilir, tekrar etmez
MOTIVASYON_QUESTIONS = [
    (
        "💙 Seni duyuyorum {name}.\n\n"
        "Sana daha iyi yardimci olabilmem icin birkaç sey sormam lazim:\n\n"
        "1️⃣ Bu duygu *ne zamandir* var? _(bugun mu, son birkaç gun mu, uzun suredir mi?)_\n\n"
        "2️⃣ En cok *hangi konuda* zorlaniyorsun?\n"
        "   _(ders/sinav mi, aile baskisi mi, arkadas ortami mi?)_\n\n"
        "3️⃣ Simdi kendini *1-10 arasi* puanlasan kac verirdin?\n\n"
        "_Rahatca yazabilirsin, seninle konusuyoruz._ 🤝"
    ),
    (
        "Hey {name}, mesajini okudum. 💙\n\n"
        "Sana yardimci olmak istiyorum ama once seni biraz daha anlamam lazim:\n\n"
        "🔹 Bugun seni en cok *ne yordu*?\n"
        "🔹 Son zamanlarda *uyku duzeni* nasil?\n"
        "🔹 Sence en buyuk *engel* ne simdi?\n\n"
        "_Istersen tek kelimeyle bile cevap verebilirsin — onemli olan konusmak._ 🌟"
    ),
    (
        "{name}, boyle hissetmen *cok normal* ve bunu paylastigin icin tesekkurler. 💙\n\n"
        "Sana ozel bir destek plani olusturmak istiyorum. Bunun icin:\n\n"
        "📌 Hangi ders(ler) seni en cok *strese* sokuyor?\n"
        "📌 Gunluk ortalama kac saat *calisiyorsun*?\n"
        "📌 Kendine ayirdigin *bos zaman* var mi?\n\n"
        "_Cevaplarina gore birlikte bir strateji olusturalim._ 🎯"
    ),
]

MOTIVASYON_RESPONSES = [
    (
        "Seni cok iyi anliyorum. Bu surec bazen bunaltici olabiliyor. "
        "Ama sana bir sey sormak istiyorum:\n\n"
        "_Cin bambusu hikayesini biliyor musun?_\n\n"
        "Bu agacin tohumu ekilir, sulanir... 4 yil boyunca toprakta tek bir filiz bile gormezsin. "
        "Ama 5. yilda aniden 27 metreye ulasir! Cunku 4 yil boyunca *kokleri* buyuyordu.\n\n"
        "Senin bugun cozdugun her soru, o koklerin bir parcasi. "
        "Netler hemen firlamayabilir ama *beynin yeni sinaptik baglar kuruyor*.\n\n"
        "Simdi sana bir sey onerebilir miyim? "
        "Sadece *5 dakika* — evet sadece 5 dakika — en sevdigin derse bak. "
        "Zeigarnik Etkisi denen bilimsel bir gercek var: Beyin baslanan isi bitirmek ister. "
        "O 5 dakika, 30 dakikaya donusecek.\n\n"
        "_Hangi dersi en cok seviyorsun? Oradan baslayalim._"
    ),
    (
        "Hey, yorgun hissetmen cok normal. "
        "Ama Stanford Universitesi'nden Carol Dweck'in soyledigi bir sey var:\n\n"
        "_'Zeka sabit degildir. Beyin bir kas gibi — calistikca guclenir.'_\n\n"
        "Bugunku yorgunlugun, beyninin buyudugunu gosteriyor. "
        "Deneme netlerin dusmus olabilir ama bu bir *tanis araci*, "
        "senin zeka olcutun degil.\n\n"
        "Birlikte su hafta neye odaklanacagimizi planlayalim mi? "
        "Kucuk hedeflerle baslayalim — her gun sadece 1 konu."
    ),
]


# ═══════════════════════════════════════════════════════════════════
# SENARYO 5: KONU AÇIKLAMASI
# ═══════════════════════════════════════════════════════════════════

KONU_ACIKLAMA_FORMAT = """*{konu}*

{aciklama}

*Gercek Hayat Ornegi:*
{ornek}

*Onemli Formul/Kavram:*
{formul}

_Bu konuda soru sormak istersen devam edelim!
Hangi kismini anlamakta zorlaniyorsun?_
"""


# ═══════════════════════════════════════════════════════════════════
# ANA ROUTER — Senaryo Tespiti
# ═══════════════════════════════════════════════════════════════════

def detect_scenario(message: str, role: str) -> Optional[dict]:
    """Mesajdan senaryo tespit et. Tespit ederse senaryo bilgisi dön."""
    msg = message.lower().strip()

    if role == "ogrenci":
        # Çalışma planı → Claude'a yönlendir, build_study_plan_context tool'u kullanacak
        if re.search(r"(calisma\s*plan|çalışma\s*plan|program\s*yap|haftalik\s*plan|plan\s*olustur|plan\s*oluştur)", msg):
            if not re.search(r"(bu\s*konu|bunu|bu\s*ders|onu|su\s*konu)", msg):
                return None  # Direkt Claude'a git — eski template yok

        # "nasıl çalışayım/çalışmalıyım" → Claude'a
        if re.search(r"nas[iı]l\s*cal[iı]s|nasıl\s*çalış", msg):
            if not re.search(r"(bu|su|o)\s*(konu|ders)", msg):
                return None  # Claude build_study_plan_context kullanacak

        # Bölüm/üniversite/hedef → güzel şablon ile bilgi topla
        # Fix 21 Nisan (yeni ogrenci "Kimya muhendisligi ne is yapar" sorusunu hedef formuna atiyor):
        # Meslek/kariyer aciklamasi istekleri (ne is yapar, ne okur, nedir, kac yil vb.) bu
        # sablondan CIKMALI → Claude'a gitsin (gercek meslek tanitimi yapsin)
        if re.search(r"(bolum|bölüm|universite|üniversite|tip|muhendis|mühendis|hukuk|hedef\w*\s*(ne|puan|olmal|nolmal))", msg):
            # Meslek tanitim sorusuysa bolum formuna atma -> Claude'a
            _meslek_sorusu = re.search(
                r"(ne\s*i[sş]\s*yapar|ne\s*yapar|ne\s*okur|nedir|ne\s*demek|"
                r"ne\s*i[yş]e\s*yarar|kac\s*y[iı]l|kaç\s*y[iı]l|i[sş]\s*bul|i[sş]\s*imkan|"
                r"hangi\s*dersler|hangi\s*konular|meslek|kariyer|maa[sş]|hangi\s*i[sş])",
                msg
            )
            if _meslek_sorusu:
                return None  # Claude meslek tanitimi yapsin

            # Bug fix 23 Nisan — Zeynep vakasi:
            # "Bu netlerle üniversite sınavında sıralama nasıl olur" → bolum formu geldi (YANLIS)
            # "sıralama/puan tahmin/netlerle/kaçıncı olurum" varsa bolum formu DEGIL,
            # Claude calculate_yks_score tool ile direkt sıralama tahmini versin.
            _puan_tahmin_sorusu = re.search(
                r"(s[iı]ralama|s[iı]ra.*nas[iı]l|kac[iı]nc[iı]|kaçıncı|"
                r"puan.*tahmin|tahmin.*puan|bu\s*netle|netlerle|"
                r"nerede.*olurum|hangi.*nere|nere.*girerim)",
                msg
            )
            if _puan_tahmin_sorusu:
                return None  # Claude calculate_yks_score kullansin

            return {"scenario": "bolum", "questions": BOLUM_QUESTIONS[0], "needs_claude": True}

        # Motivasyon/stres/duygusal — bağlam toplama sorusu sor, Claude analiz yapsın
        # "istiyorum" tek basina motivasyon degil — hedef/bolum olabilir (ITU istiyorum)
        if re.search(r"(motivasyon|moral|pes\s*ed|pes\s*ettim|birak\w*\s*ders|bırak\w*\s*ders|yoruldum|yapam[iı]y|becer|sikil|sıkıl|umut\w*\s*kalmad|stres|kaygi|kaygı|korku|basara|kotuyum|kötüyüm|uzgunum|üzgünüm|ask\s*ac[iı]|aşk\s*ac|istemiy\w+\s+ders|ders\s*istem|mutsuz|uzgun|üzgün|agla|ağla|bunald|dayanam)", msg):
            # "istiyorum" ile bolum/hedef karismasin
            if re.search(r"(istiyorum|istiyorummm)", msg) and re.search(r"(mimarlik|mimarlık|tip|tıp|muhendis|mühendis|hukuk|bolum|bölüm|universite|üniversite)", msg):
                return None  # Bolum rehberligi — Claude'a gitsin
            from motivation_library import get_motivasyon_sorusu
            q = get_motivasyon_sorusu("{name}")  # {name} placeholder kalsin, try_fast_response dolduracak
            return {"scenario": "motivasyon", "questions": q, "needs_claude": True}

        # Konu açıklaması
        if re.search(r"(anlat|acikla|açıkla|nedir|ne\s*demek|formul|formül|konu.*anlam|anlamiyorum|anlamıyorum)", msg):
            return {"scenario": "konu", "needs_claude": True}

    return None


# ═══════════════════════════════════════════════════════════════════
# OLLAMA İÇİN SENARYO PROMPTLARİ
# ═══════════════════════════════════════════════════════════════════

OLLAMA_SCENARIO_PROMPTS = {
    "plan": """Ogrenci calisma plani istiyor. Once su sorulari sor:
1. Hangi gunler ve saatler musait?
2. Gunluk kac saat calisma hedefliyor?
3. Oncelikli dersler hangileri?
Bu bilgileri topla, sonra plani olusturmak icin hazirlan.""",

    "bolum": """Ogrenci bolum/universite hedefi soruyor. Sorular sor:
1. Hedef bolumu ne?
2. Sayisal/sozel/EA?
3. Hedef universiteler?
Bilgileri topla, samimi ve motive edici ol.""",

    "motivasyon": """Ogrenci motivasyon dusuklu yasıyor. KESINLIKLE yargilama.
Cin bambusu hikayesini anlat, Zeigarnik 5dk kuralini oner, Dweck buyume zihniyetinden bahset.
Samimi, sicak, anlayisli ol. Sonra kucuk bir adim oner.""",

    "konu": """Ogrenci akademik konu aciklamasi istiyor.
Konuyu anlasilir dilde acikla, gercek hayat ornegi ver, formul varsa yaz.
Sonra 'Hangi kismini anlamakta zorlaniyorsun?' diye sor.""",
}
