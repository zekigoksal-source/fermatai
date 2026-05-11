"""
FermatAI WP Yanit Sablonlari — Claude kalitesinde gorsel standart.

Her sablon Claude tarafindan tasarlandi. Fast_response ve Ollama
bu sablonlari kullanarak ayni gorsel kaliteyi korur.

WhatsApp markdown:
- *bold* → kalın
- _italic_ → italik
"""

# ═══════════════════════════════════════════════════════════════════
# SELAMLAMA — ROL BAZLI
# ═══════════════════════════════════════════════════════════════════

SELAMLAMA = {
    "admin": (
        "Merhaba *Zeki Bey*! 👋\n\n"
        "FermatAI hazir ve bekliyor.\n\n"
        "📊 Ogrenci analizi\n"
        "👨‍🏫 Ogretmen takibi\n"
        "🏫 Kurum raporlari\n"
        "⚙️ Sistem yonetimi\n\n"
        "_Ne uzerinde calisalim?_"
    ),

    "mudur_mahsum": (
        "Hos geldiniz *Sayin Mudurum*! 👋\n\n"
        "FermatAI emrinizde.\n\n"
        "📊 Ogrenci ve sinif analizleri\n"
        "👨‍🏫 Ogretmen performans takibi\n"
        "📋 Rehberlik raporlari\n"
        "📅 Haftalik program ozeti\n\n"
        "_Hangi konuda yardimci olabilirim?_"
    ),

    "mudur_duygu": (
        "Merhaba *Duygu Hanim*! 👋\n\n"
        "FermatAI hazir.\n\n"
        "📊 Akademik analiz ve raporlama\n"
        "📝 Sinav degerlendirme\n"
        "👥 Ogrenci takibi\n\n"
        "_Size nasil yardimci olabilirim?_"
    ),

    "mudur_duygu_ozel": (
        "Merhaba *Duygu Hanim*! 👋✨\n\n"
        "Biliyorsunuz, bu sistemi yaratan dehanin esi olmak "
        "basli basina bir ayricalk! 🧠\n\n"
        "Bugun nasil yardimci olabilirim?\n\n"
        "📊 Ogrenci analizleri\n"
        "📝 Sinav degerlendirme\n"
        "💰 Muhasebe kayitlari\n"
        "👥 Ogretmen takibi\n\n"
        "_Ne uzerinde calisalim?_"
    ),

    "mudur_orsel": (
        "Nasilsin *sadicim*! 😄👋\n\n"
        "Nabıyon bakam, hayrola?\n\n"
        "📊 Ogrenci analizleri\n"
        "👨‍🏫 Ogretmen programlari\n"
        "📝 Sinav degerlendirme\n"
        "🔬 Fizik konu analizleri\n\n"
        "_Ne bakalim bugun sadicim?_"
    ),

    "mudur_default": (
        "Merhaba! 👋\n\n"
        "FermatAI hazir. Ogrenci, ogretmen ve kurum hakkinda "
        "bilgi alabilirsiniz.\n\n"
        "_Ne sormak istersiniz?_"
    ),

    "yonetim_bilge": (
        "Merhaba *Bilge Hanim*! 👋\n\n"
        "FermatAI emrinizde. Size nasil yardimci olabilirim?\n\n"
        "📊 *Ogrenci analizleri* — akademik performans, trend\n"
        "📈 *Kurum raporlari* — sinif bazli karsilastirma\n"
        "👨‍🏫 *Ogretmen takibi* — etut yogunlugu, program\n"
        "📋 *Stratejik degerlendirme* — hedef analizi\n\n"
        "_Hangi konuda detayli analiz yapmak istersiniz?_"
    ),

    "yonetim_murathan": (
        "Merhaba *Murathan Bey*! 👋\n\n"
        "FermatAI hazir. Kurumun guncel durumu hakkinda\n"
        "detayli bilgi ve analiz sunabilirim.\n\n"
        "📊 *Akademik performans* — ogrenci bazli ve sinif bazli\n"
        "📈 *Trend analizleri* — donem karsilastirmasi\n"
        "👨‍🏫 *Operasyonel verimlilik* — ogretmen ve etut\n"
        "🎯 *Stratejik planlama* — hedef ve projeksiyon\n\n"
        "_Hangi konuda calisalim?_"
    ),

    "rehber": (
        "Merhaba *{name}*! 👋\n\n"
        "Bugun size nasil yardimci olabilirim?\n\n"
        "📊 Ogrenci akademik analizi\n"
        "📅 Ogretmen ders programlari\n"
        "📝 Etut planlama\n"
        "📋 Rehberlik notlari\n\n"
        "_Hangi ogrenci veya sinif hakkinda bakmak istersiniz?_"
    ),

    "ogretmen": (
        "Merhaba *{name}*! 👋\n\n"
        "Bugun size nasil yardimci olabilirim?\n\n"
        "📅 Ders programiniz\n"
        "📊 Sinifinizdaki ogrenci durumlari\n"
        "📝 Ogrenci etut ihtiyaci bildirme\n\n"
        "_Bugunun programini gormek ister misiniz?_"
    ),

    "ogrenci": (
        "Merhaba *{name}*! 😊 Nasilsin bugun?\n\n"
        "Seninle neler yapabiliriz:\n\n"
        "📊 Son deneme analizin\n"
        "🎯 Zayif konularin ve calisma onerileri\n"
        "📅 Haftalik calisma plani\n"
        "🎓 Hedef bolum rehberligi\n"
        "📝 Herhangi bir konu hakkinda soru\n\n"
        "_Ne hakkinda konusmak istersin?_"
    ),
}

# ═══════════════════════════════════════════════════════════════════
# SELAMLAMA ÇEŞITLILIK HAVUZU (Oturum 18)
# Karakter manifestine uygun: kisa, sicak, dogal, listeleme YOK,
# her cevapta ayni sablon degil. Random pick + son kullanilani reddet.
# ═══════════════════════════════════════════════════════════════════

SELAMLAMA_VARYASYON = {
    "admin": [
        "*Zeki Bey* 👋 Hazırım. Bugün ne üzerinde duralım?",
        "Hoş geldin *{name}* — sistem ayakta, sen söyle.",
        "*Zeki Bey* selam. Komuta sende, ne yapalım?",
        "Buradayım *{name}*. Bugünün gündemi nedir?",
        "Selam *{name}* — gözler tetkikte, kulaklar açık. 🎯",
        "Hoş geldin *Zeki Bey*. Sade ve net — ne yapıyoruz?",
    ],
    "mudur_mahsum": [
        "*Sayın Müdürüm* 🎩 hoş geldiniz. Buyrun, dinliyorum.",
        "Hoş geldiniz *Müdürüm* — gündem sizde, hazırım.",
        "*Mahsum Bey*, buyrun. Bugün nereye odaklanalım?",
        "Selam *Müdürüm* — saha rapora hazır, sorun.",
        "*Sayın Müdürüm*, nasıl yardımcı olabilirim bugün?",
    ],
    "mudur_duygu": [
        "*Duygu Hanım* 👋 hoş geldiniz. Ne üzerinde çalışalım?",
        "Hoş geldiniz *{name}* — bugün ne sormak istersiniz?",
        "Selam *Duygu Hanım* — buyrun, dinliyorum.",
        "*Duygu Hanım*, hazırım. Hangi öğrenciden başlayalım?",
        "Hoş geldiniz — sistem hazır, gündem sizde.",
    ],
    "mudur_orsel": [
        "Nasılsın *sadıcım*! 😄 Nabıyon bakam?",
        "Selam *sadıcım* — hayrola, ne yapıyoruz?",
        "*Örsel hocam* 👋 buyrun, dinliyorum.",
        "Sadıcım hoş geldin — ne bakalım bugün?",
        "*Sadıcım* 🎯 gündem sende, söyle.",
        "Hey *sadıcım* 😎 sistem tetikte, ne lazım?",
        "*Örsel Bey* hoş geldin — SGM gündemi ne?",
    ],
    "mudur_default": [
        # 25.43-ITER3 (Neo: müdür için proaktif liderlik tonu, "pasif değil" judge feedback):
        "Hoş geldiniz *{name}* 🎯 Kurum nabzı sizde — hangi raporu çekelim?",
        "Selam *{name}* — bugün sınıf trendleri, öğretmen performansı veya öğrenci durumu hazır.",
        "*{name}*, FermatAI yönetim modülü emrinizde. Akademik özet mi, finansal mı?",
        "Hoş geldiniz *{name}* — kurum istatistikleri güncel, sınıf bazlı analiz hazır.",
        "*{name}* 👔 size haftalık panorama veya kritik sinyal raporu sunabilirim.",
    ],
    "yonetim_bilge": [
        "Merhaba *Bilge Hanım* 👋 Hangi konuda analiz yapalım?",
        "Hoş geldiniz *Bilge Hanım* — stratejik gündem sizde.",
        "*Bilge Hanım* 🎯 akademik panorama hazır, buyrun.",
        "Selam *Bilge Hanım* — hangi sınıf/öğretmen üzerinde duralım?",
    ],
    "yonetim_murathan": [
        "Merhaba *Murathan Bey* 👋 Kurumun nabzını mı alalım?",
        "Hoş geldin *Murathan Bey* — trend + operasyonel durum hazır.",
        "*Murathan Bey* 🎯 strateji masası açık, nereden başlayalım?",
        "Selam *Murathan Bey* — ODTÜ düzeninde, sade ve net. Buyrun.",
    ],
    "ogrenci": [
        # 25.43-ITER5 (ton): selamlamaya selamlama don, sicaklik + motivasyon
        "Günaydın *{name}*! ☀️ Bugün hangi konuda ilerleyelim?",
        "Selam *{name}*! 👋 Hazır mısın bugüne? 💪",
        "Merhaba *{name}*! 😊 Bugün seninle ne çalışacağız?",
        "Hoş geldin *{name}*! ⚡ Bana net/konu/program — söyle, başlayalım.",
        "Selam *{name}*! 🌟 Sınava odaklanmaya hazır mıyız?",
        "Merhaba *{name}*! 🎯 Bugün bir adım daha — hangi ders?",
        "Hoşgeldin *{name}*! 🚀 Deneme analizi mi, konu çalışması mı?",
        "Selam *{name}*! 💫 Akademik gündem sende, ben hazırım.",
        "Günaydın *{name}*! 📚 Sınav yolculuğunda devam — neye bakalım?",
        "Merhaba *{name}*! 🎓 Bugünün planı: deneme/konu/strateji?",
    ],
    "ogretmen": [
        # 25.43-ITER5 (ton): profesyonel + actionable, "*Test* Hocam" yerine isim+actionable
        "Merhaba *{name}* Hocam! Size nasıl yardımcı olabilirim?",
        "Günaydın *{name}* Hocam ☀️ Sınıf analizi, etüt veya program — hangisi?",
        "Hoş geldiniz *{name}* Hocam — bugünkü gündem: deneme sonuçları mı, etüt mü?",
        "Selam *{name}* Hocam 📚 Sınıf, öğrenci veya program — buyrun.",
        "Merhaba *{name}* Hocam! 🎯 Öğrenci durumu, etüt önerisi veya analiz — hazırım.",
        "Günaydın Hocam — sınıf raporları güncel, hangi açıdan başlayalım?",
        "Hoş geldiniz *{name}* Hocam 🎓 Risk takibi, etüt planı veya rapor?",
    ],
    "veli": [
        # 25.43-ITER5 (ton): veli icin profesyonel ton + actionable + saygi
        "Merhaba *Sayın Velim* 👋 Size nasıl yardımcı olabilirim?",
        "Günaydın *Sayın Velim* ☀️ Çocuğunuzun akademik durumu için buradayım.",
        "Hoş geldiniz *Sayın Velim* — rehberlik veya genel bilgi, hangisi?",
        "Merhaba 👋 Çocuğunuzla ilgili haftalık özet veya randevu — buyrun.",
        "İyi günler — veli iletişim hattı emrinizde, dilediğiniz konuyu sorabilirsiniz.",
    ],
    "rehber": [
        # 25.43-ITER5 (ton): rehber daha proaktif, sıcak + actionable
        "Merhaba *{name}* Hocam! Hangi öğrenci üzerinde duralım?",
        "Günaydın *{name}* Hocam ☀️ Bugün duygu takibi mi, akademik mı?",
        "Hoş geldiniz *{name}* Hocam — risk altındaki öğrenci listesi hazır, buyrun.",
        "*{name}* Hocam 👋 brans öğretmen önerileri veya rehberlik notları — hangisi?",
        "Merhaba Hocam — duygu sinyalleri ve akademik panorama hazır, başlayalım.",
    ],
}


def pick_selamlama(role: str, name: str = "", phone: str = "default") -> str:
    """Karaktere uygun, cesitli, son kullanilani tekrar etmeyen selamlama."""
    import random as _r
    if not hasattr(pick_selamlama, "_history"):
        pick_selamlama._history = {}
    history = pick_selamlama._history

    # Mudur/Yonetim altrol tespiti (isim bazli) — 22.1n karsilama isim karisikligi fix
    effective_role = role
    if role == "mudur":
        n = (name or "")
        if "Mahsum" in n or "mahsum" in n.lower():
            effective_role = "mudur_mahsum"
        elif "Duygu" in n or "duygu" in n.lower():
            effective_role = "mudur_duygu"
        elif "Örsel" in n or "Orsel" in n or "orsel" in n.lower():
            effective_role = "mudur_orsel"
        else:
            effective_role = "mudur_default"
    elif role == "yonetim":
        n = (name or "")
        if "Bilge" in n or "bilge" in n.lower():
            effective_role = "yonetim_bilge"
        elif "Murathan" in n or "murathan" in n.lower():
            effective_role = "yonetim_murathan"
        else:
            effective_role = "mudur_default"

    pool = SELAMLAMA_VARYASYON.get(effective_role)
    if not pool and role == "mudur":
        pool = SELAMLAMA_VARYASYON.get("mudur_default")
    if not pool:
        pool = SELAMLAMA_VARYASYON.get("ogrenci")
    if not pool:
        return f"Merhaba *{name}*! 👋"

    key = f"{phone}:{role}"
    recent = history.get(key, [])
    candidates = [i for i in range(len(pool)) if i not in recent[-3:]]
    if not candidates:
        candidates = list(range(len(pool)))
    idx = _r.choice(candidates)
    recent.append(idx)
    if len(recent) > 5:
        recent = recent[-5:]
    history[key] = recent

    msg = pool[idx]
    if "{name}" in msg:
        first = (name.split()[0] if name else "")
        msg = msg.replace("{name}", first or "arkadaşim")
    return msg


# ═══════════════════════════════════════════════════════════════════
# YOKLAMA / DURUM
# ═══════════════════════════════════════════════════════════════════

YOKLAMA_CEVAP = "Evet, buradayim! 😊 Size nasil yardimci olabilirim?"

KIMLIK = {
    "admin": "Sen *Neo*'sun, Zeki Bey! 🎯\nFermat AI'nin mimari ve sistem efendisi.",
    "mudur_mahsum": "Siz *Sayin Mudurum*, Mahsum Yalcin! 🏫\nFermat Egitim Kurumlari'nin degerli muduru.",
    "mudur_duygu": "Siz *Duygu Hanim*! 🌟\nFermat Egitim Kurumlari mudur yardimcisi.",
    "ogrenci": "Sen *{name}*! 🎓\nFermat Egitim Kurumlari ogrencisi.",
}

# ═══════════════════════════════════════════════════════════════════
# GİZLİLİK — KURUMSAL TON (teknik detay yok)
# ═══════════════════════════════════════════════════════════════════

GIZLILIK_CEVAP = (
    "🔒 *Veri Guvenligi Politikamiz*\n\n"
    "Tum konusmalariniz kurumsal guvenlik standartlarimiz "
    "dahilinde korunmaktadir.\n\n"
    "✅ Kisisel verileriniz *KVKK* kapsaminda guvendedir\n"
    "✅ Bilgileriniz yalnizca egitim surecinin iyilestirilmesi amaciyla kullanilir\n"
    "✅ Verileriniz ucuncu taraflarla *paylasilmaz*\n"
    "✅ Kurum yonetimi, egitim kalitesini saglamak adina surecleri takip eder\n\n"
    "_Bu, tum profesyonel egitim kurumlarinin standart uygulamasidir._"
)

# ═══════════════════════════════════════════════════════════════════
# YETKİ RED — KURUMSAL TON
# ═══════════════════════════════════════════════════════════════════

YETKI_RED = (
    "🔐 *Yetki Bilgilendirmesi*\n\n"
    "Rol ve yetki degisiklikleri bu kanal uzerinden yapilamaz.\n\n"
    "Mevcut yetkiniz dahilinde size yardimci olmaktan "
    "mutluluk duyarim.\n\n"
    "_Baska bir konuda yardimci olabilir miyim?_"
)

# ═══════════════════════════════════════════════════════════════════
# YETENEKLER — ROL BAZLI ("Ne yapabilirsin?" sorusuna cevap)
# ═══════════════════════════════════════════════════════════════════

def get_yetenekler(role: str, name: str = "") -> str:
    """Rol bazli yetenek tanitimi — etkileyici, kurumsal, sci-fi hissiyati."""
    first = name.split()[0] if name else ""

    if role == "ogrenci":
        return (
            f"*{first}*, sana bir sey soyleyeyim — sen simdi siradan bir chatbot'la konusmuyorsun 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 *FermatAI — Kisiye Ozel YKS Zeka Motoru*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ben senin tum deneme verilerini, konu konu guclu ve zayif yanlarini, "
            "devamsizlik oruntunu, calisma aliskanliklarin ve hatta motivasyon trendini "
            "bir arada analiz edebilen bir *egitim zekasiyim*.\n\n"
            "Iste seninle yapabileceklerimiz:\n\n"
            "📊 *Deneme Rontgeni*\n"
            "Sadece netlerin degil — hangi konuda yukseliyorsun, nerede kayip var, "
            "hangi derste ivme kazandin, hangi ders dikkat istiyor? "
            "Tum bunlari *tek mesajla* ozetlerim.\n\n"
            "🎯 *Zayif Nokta Haritasi*\n"
            "Tum denemelerini tariyorum ve en cok puan kaybettigin konulari cikariyorum. "
            "Sadece \"fizik zayif\" degil — _hangi fizik konusu, kac soru kacirdin, "
            "ne kadar net kazanabilirsin_ seviyesinde.\n\n"
            "📸 *Gercek YKS Cikmis Sorular — Gorselli!*\n"
            "Sana MEB'in resmi cikmis soru sayfalarini _fotograf olarak_ gonderirim. "
            "\"Manyetizma 2024 sorusunu goster\" de, orijinal sinav sayfasi onunde olsun. "
            "Sonra birlikte adim adim cozelim.\n\n"
            "📈 *YKS Soru Haritasi*\n"
            "Her dersten hangi konudan kac soru ciktigini 2018'den bugune bilirim. "
            "\"Turev her yil 4-5 soru, burayi saglama al\" gibi *stratejik* bilgiler.\n\n"
            "📚 *Konu Anlatimi ve Soru Cozumu*\n"
            "Formul mü lazim, kavram mi, cozum teknigi mi? Soruyu yaz veya fotografini at — "
            "adim adim cozerim.\n\n"
            "🎓 *MEB OGM Resmi Kaynak Yonlendirme* (YENİ)\n"
            "\"TYT Matematik test cozmek istiyorum\" de, MEB'in resmi 3 Adım Soru Bankası "
            "linkini göndereyim. Konu özeti PDF, video ders, çıkmış soru — _hepsi ücretsiz, "
            "MEB onaylı._\n\n"
            "🎯 *Anonim Arkadas Kiyaslamasi* (YENİ)\n"
            "Aynı sınıftaki diğer arkadaşların ortalamasıyla kendi puanını kıyasla. "
            "Kimse adını görmez, sen de onların. Sadece senin nerede olduğun belli olur.\n\n"
            "🧠 *Konu Hafizasi* (YENİ)\n"
            "Geçen sefer konuştuğumuz konuyu hatırlarım. \"Fotoelektrik'i geçen ay sorduk, "
            "tekrar mı bakalım?\" diyebilirim — kaldığın yerden devam.\n\n"
            "📅 *Sana Ozel Calisma Plani*\n"
            "Zayif konularin, sinav takvimi ve konu dagilimina gore "
            "*sana ozel* gunluk program olusturuyorum.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 _Ve {first} — benimle konusurken hic kasmana gerek yok. "
            "\"Fizigim cok kotu\" de yeter, ben ne yapman gerektigini bulurum. "
            "Foto at anlarim, soru yaz cozerim, derdini anlat dinlerim. "
            "Sen sadece yaz, gerisi bende._ \n\n"
            f"_Hadi {first}, nereden baslayalim?_ 🎯"
        )

    elif role == "ogretmen":
        return (
            f"*{first} Hocam*, FermatAI sizin icin neler yapabilir bir bakis atmanizi isterim 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "👨‍🏫 *FermatAI — Akilli Ogretmen Asistani*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Tum ogrenci verilerini, deneme trendlerini, devamsizlik oruntusunu "
            "ve etut istatistiklerini bir arada degerlendiren bir *analitik zekayim*.\n\n"
            "📊 *Ogrenci Performans Haritasi*\n"
            "Sinifinizdaki her ogrencinin ders ders trendi, zayif konulari, "
            "devamsizligi ve etut katilimi — _tek mesajla_ kapsamli profil.\n\n"
            "🔍 *Sinif Bazli Karsilastirma*\n"
            "Siniflar arasi net ortalamasi, en cok zorlanan konular, "
            "basari siralamasi — veriye dayali karar alin.\n\n"
            "📸 *MEB Resmi Cikmis Soru Bankasi*\n"
            "Konu ve yil bazli YKS cikmis soru katalogu. "
            "Dersinizden hangi konudan kac soru ciktigini gorun, "
            "ogrenciye direkt gorsel gonderin.\n\n"
            "📅 *Program, Etut ve Takvim*\n"
            "Haftalik ders programiniz, etut gecmisiniz, "
            "ogretmen karsilastirma istatistikleri.\n\n"
            "📈 *Stratejik Konu Dagilimi*\n"
            "Dersinizden 2018-2025 arasi hangi konudan kac soru cikmis — "
            "ders planlamanizi buna gore sekillendirin.\n\n"
            "🎓 *MEB OGM Resmi Kaynak Katalogu* (YENİ)\n"
            "Ogrencilerinize MEB resmi 3 Adım Soru Bankası, Konu Özeti PDF, "
            "Video dersleri için direkt link atın. \"AYT Fizik soru bankası göster\" deyin, "
            "anında link gelir.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 _Hocam, kafaniza takilan seyi aynen yazin — "
            "\"Ali'nin son durumu ne\", \"bu sinifta kimler zorlaniyor\", "
            "\"bu hafta kac etut yaptim\" gibi. "
            "Resmi komut yazmaniza gerek yok, ben anlarim._\n\n"
            "_Nasil yardimci olabilirim Hocam?_ 📋"
        )

    elif role == "rehber":
        return (
            f"*{first} Hocam*, FermatAI rehberlik modulu ile neler yapilabilecegine bir goz atin 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧭 *FermatAI — Rehberlik Zeka Motoru*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Akademik veri, duygu analizi, davranis oruntuleri ve "
            "gorusme gecmisini bir arada degerlendiren bir *pedagogik zekayim*.\n\n"
            "📊 *360 Derece Ogrenci Profili*\n"
            "Deneme netleri, trend grafigi, devamsizlik, etut katilimi, "
            "zayif konular, guclu yanlar — _tek isimle_ tum tablo.\n\n"
            "🧠 *Duygu ve Motivasyon Radarı*\n"
            "Ogrenci mesajlarindan stres, kaygi ve motivasyon dususu "
            "sinyallerini otomatik algilarim. Risk altindaki ogrencileri "
            "*proaktif* olarak bildiririm.\n\n"
            "📝 *Gorusme Gecmisi ve Takip*\n"
            "Tum rehberlik gorusme notlari kayitli — ogrenci bazli kronolojik erisim.\n\n"
            "📸 *Cikmis Soru ile Interaktif Pratik*\n"
            "Ogrencinin zayif konusundan gercek YKS sorusu gonderip "
            "birlikte cozum yapabilirsiniz.\n\n"
            "📅 *Etut Planlama ve Ogretmen Musaitligi*\n"
            "Ihtiyaca gore etut olusturma, uygun ogretmen ve saat onerileri.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 _Hocam, bir ogrenci ismi soylemekle baslayabilirsiniz — "
            "gerisi bende. \"Zeynep son zamanlarda nasil\" yazmaniz yeter, "
            "ben akademik + duygusal tum tabloyu ozetlerim._\n\n"
            "_Hangi ogrenciyle baslayalim?_ 🎯"
        )

    elif role in ("mudur", "yonetim"):
        hitap = f"*{first}*" if first else "Sayin Mudurum"
        return (
            f"{hitap}, FermatAI yonetim modulu emrinizde 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🏫 *FermatAI — Kurum Yonetim Zekasi*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Ogrenci performansi, ogretmen etkinligi, devamsizlik oruntuleri "
            "ve kurum geneli trendleri bir arada degerlendiren "
            "bir *yonetim karar destek sistemi*.\n\n"
            "📊 *Anlik Kurum Fotografi*\n"
            "Ogrenci sayisi, deneme katilim oranlari, aktif etut, "
            "devamsizlik ortalamalari — kurumun nabzi tek bakista.\n\n"
            "📈 *Ogrenci Bazli Derin Analiz*\n"
            "Herhangi bir ogrencinin deneme trendi, zayif konulari, "
            "devamsizlik, etut gecmisi, rehberlik notlari — kapsamli profil.\n\n"
            "👨‍🏫 *Ogretmen Performans Karsilastirmasi*\n"
            "Etut yogunlugu, ders dagilimi, siniflar arasi basari farklari — "
            "karsilastirmali veriler.\n\n"
            "📸 *MEB Cikmis Soru Bankasi*\n"
            "4,400+ cikmis soru kaydi — konu ve yil bazli katalog, gorsel paylasim.\n\n"
            "🔎 *Ozel Sorgular*\n"
            "\"En basarili 10 ogrenci\", \"devamsizlik raporu\", "
            "\"fizik etut istatistigi\" — sorun, cevap gelsin.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 _Akliniza gelen her soruyu dogal bir sekilde yazabilirsiniz — "
            "\"bugun kim gelmemis\", \"siniflar arasi durum\", "
            "\"mart ayi etut raporu\" gibi. "
            "Komut ezberlemenize gerek yok, ben anlarim._\n\n"
            "_Emrinizdeyim, ne ile baslayalim?_ 📋"
        )

    elif role == "admin":
        return (
            f"*{first}*, FermatAI tam kapasite ile hazır ⚡\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ *FermatAI — Merkez Komuta*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 *Tam Veri Erişimi*\n"
            "Öğrenci, öğretmen, deneme, devamsızlık, etüt, rehberlik — "
            "tüm veritabanına sınırsız erişim.\n\n"
            "🧠 *Gelişmiş Analitik Motor*\n"
            "Özel SQL sorguları (AST guard'lı), karşılaştırmalı analizler, "
            "trend raporları, konu dağılım istatistikleri.\n\n"
            "📸 *RAG + Çıkmış Soru Bankası*\n"
            "5,500+ kayıt — AYT Sayısal, TYT, AYT EA (2024 Fotoelektrik dahil, 337 multi-soru splitted). "
            "Semantik arama + görsel paylaşım.\n\n"
            "🎓 *MEB OGM Yönlendirme* (YENİ)\n"
            "47 resmi MEB kaynağı (3 Adım Soru Bankası, Konu Özeti PDF, Video) — "
            "Claude direkt link üretir.\n\n"
            "🔭 *Atlas Self-Observing* (22.1)\n"
            "Sistem kendini gözlemliyor; bug/regresyon/frustration otomatik tespit + öneri.\n\n"
            "🧭 *YÖK Atlas Entegrasyonu*\n"
            "35,584 kayıt, 4 yıllık trend, öğrenci net→bölüm tahmini.\n\n"
            "📖 *Canlı KALDIGIM Okuyucu*\n"
            "Neo sorduğunda son oturum güncellemelerini tool ile oku, değişiklikleri anlat.\n\n"
            "✏️ *LMS Entegrasyonu*\n"
            "Etüt yazma, rehberlik notu, otomatik kayıt işlemleri (audit logged).\n\n"
            "🔐 *Güvenlik Katmanı*\n"
            "SQL AST guard, hack tracker (persistent), OTP brute koruma, "
            "hassas veri maskeleme, response cleaner.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 _Aklına ne gelirse yaz — veriyi ben bulurum, "
            "yorumu ben yaparım, sunumu ben hazırlarım._\n\n"
            f"_Emrinizdeyim Reis._ ⚡"
        )

    # Default / veli / guest
    return (
        "Merhaba! Ben *FermatAI* — Fermat Egitim Kurumlari'nin "
        "dijital egitim asistaniyim 🚀\n\n"
        "Akademik analiz, deneme degerlendirme, konu anlatimi ve "
        "cikmis soru gorselleri gibi bir cok konuda "
        "yardimci olabilirim.\n\n"
        "_Nasil yardimci olabilirim? Yazmaniz yeterli._ 😊"
    )


# ═══════════════════════════════════════════════════════════════════
# BAĞLAM SORGULAMA (CLARIFICATION)
# ═══════════════════════════════════════════════════════════════════

CLARIFICATION_TEMPLATES = {
    "belirsiz_ogrenci": (
        "Sana yardımcı olabilmem için biraz daha detay verir misin? 😊\n\n"
        "1️⃣ *Sınav sonucun* — son deneme analizi\n"
        "2️⃣ *Zayıf konular* — çalışman gereken yerler\n"
        "3️⃣ *Çalışma planı* — kişisel program\n"
        "4️⃣ *Çıkmış soru* — konu/yıl bazlı gerçek YKS soruları\n"
        "5️⃣ *MEB OGM linki* — resmi 3 Adım Soru Bankası\n"
        "6️⃣ *Konu anlat* — fizik/matematik/biyoloji vs.\n\n"
        "_Numara yaz, ya da direkt konuşalım — 'fotoelektriği anlat', 'TYT matematik test ver' gibi._ 🎯"
    ),
    "belirsiz_admin": (
        "Ne hakkinda bilgi almak istiyorsunuz? 📋\n\n"
        "📊 *Ogrenci* — akademik analiz, profil\n"
        "👨‍🏫 *Ogretmen* — etut yogunlugu, program\n"
        "🏫 *Kurum* — genel istatistik, rapor\n"
        "📅 *Program* — gunluk/haftalik plan\n\n"
        "_Detay verin, daha iyi yardimci olayim._"
    ),
    "belirsiz_bilgi": (
        "*{name}* hakkinda hangi bilgiyi istiyorsunuz?\n\n"
        "📝 *Akademik durum* — sinav netleri, siralama\n"
        "📊 *Deneme kiyaslama* — son 3 deneme trendi\n"
        "📅 *Devamsizlik* — toplam gelmedigi gun\n"
        "📚 *Etut durumu* — aldigi etut sayisi\n"
        "🎯 *Zayif konular* — calismasi gereken alanlar\n\n"
        "_Numara veya konu yazin._"
    ),
}

# ═══════════════════════════════════════════════════════════════════
# ÖĞRENCİ PROFİL FORMATI — fast_response ve Claude aynı şablon
# ═══════════════════════════════════════════════════════════════════

def format_student_profile(name, sinif, exam=None, devam=None, topics=None, etut=None):
    """Standart ogrenci profil formati."""
    lines = [f"👤 *{name}* — {sinif}\n"]

    if exam:
        lines.append(f"📝 *Son Deneme:* {exam.get('exam_name', '?')}")
        if exam.get('toplam') is not None:
            lines.append(f"   Toplam: *{exam['toplam']:.1f}* net")
        subjects = []
        for key, label in [('turkce','Tur'), ('matematik','Mat'), ('fizik','Fiz'),
                           ('kimya','Kim'), ('biyoloji','Bio'), ('geometri','Geo')]:
            v = exam.get(key)
            if v and v > 0:
                subjects.append(f"{label}: {v:.1f}")
        if subjects:
            lines.append(f"   {' | '.join(subjects)}")
        lines.append("")

    if devam:
        saat = devam.get('toplam_saat', 0)
        emoji = "🔴" if saat > 30 else "🟡" if saat > 15 else "🟢"
        lines.append(f"{emoji} *Devamsizlik:* {saat} saat")

    if etut:
        lines.append(f"📚 *Etut:* {etut.get('toplam', 0)} toplam ({etut.get('yapildi', 0)} katilim)")

    if topics:
        # INVERSION FIX (Berf bug 10 May): sinav_hata_yuzdesi = HATA %
        lines.append(f"\n🎯 *Gelisim Alanlari:*")
        for t in topics[:3]:
            hata = t.get('sinav_hata_yuzdesi', 0) or 0
            basari = max(0.0, min(100.0, 100.0 - float(hata)))
            emoji = "🔴" if hata >= 50 else "🟡" if hata >= 25 else "🟢"
            lines.append(f"   {emoji} {t.get('ders','?')}: {t.get('konu','?')[:35]} (basari: %{basari:.0f})")

    lines.append(f"\n_Daha detayli analiz icin 'detayli raporla' yazabilirsiniz._")
    return "\n".join(lines)


def format_teacher_summary(name, brans, summary=None, program=None, son_etut=None):
    """Standart ogretmen ozet formati."""
    lines = [f"👨‍🏫 *{name}* — {brans}\n"]

    if summary:
        lines.append(f"📊 *Sezon Ozeti:*")
        lines.append(f"   Toplam etut: *{summary.get('toplam_etut', 0)}*")
        lines.append(f"   Ogrenci sayisi: *{summary.get('ogrenci_sayisi', 0)}*")
        lines.append(f"   Ders saati: *{summary.get('toplam_ders', 0)}*")

    if son_etut:
        lines.append(f"\n📅 Son etut: {son_etut}")

    if program:
        gun_str = ", ".join(f"{p['gun']}({p['ders_sayisi']})" for p in program)
        lines.append(f"\n📅 *Haftalik Program:* {gun_str}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# SOHBET / MUHABBET — ÖĞRENCİ İÇİN SAMİMİ
# ═══════════════════════════════════════════════════════════════════

SOHBET_OGRENCI = [
    (
        "Iyiyim {name}, tesekkurler! 😊 Sen nasilsin?\n\n"
        "Bugun kendini nasil hissediyorsun? "
        "Enerjik mi, yorgun mu, yoksa tam gaz mi? 💪\n\n"
        "_Bir ders hakkinda konusmak ister misin, yoksa sadece sohbet mi edelim?_"
    ),
    (
        "Iyiyim {name}! 😊 Sen anlatabilirsin?\n\n"
        "Dersler nasil gidiyor bu aralar? "
        "Bir konu var mi kafani kurcalayan?\n\n"
        "_Istersen son deneme analizine bakalim, istersen sohbet edelim._ 🎯"
    ),
    (
        "Tesekkurler {name}, her sey yolunda! 😊\n\n"
        "Peki sen? Bugun okulda neler oldu?\n\n"
        "_Merak ettigin bir konu varsa yazabilirsin, "
        "yoksa planin hakkinda konusabiliriz._ 📚"
    ),
]

# ═══════════════════════════════════════════════════════════════════
# MOTİVASYON DÜŞÜKLÜĞÜ — PEDAGOJİK
# ═══════════════════════════════════════════════════════════════════

MOTIVASYON_YANITLARI = [
    (
        "Seni cok iyi anliyorum {name}. Bu surec bazen bunaltici olabiliyor. 💙\n\n"
        "Ama sana bir sey sormak istiyorum:\n\n"
        "_Cin bambusu hikayesini biliyor musun?_\n\n"
        "Bu agacin tohumu ekilir, sulanir... *4 yil* boyunca toprakta tek bir filiz "
        "bile gormezsin. Ama 5. yilda aniden *27 metreye* ulasir!\n\n"
        "Cunku 4 yil boyunca *kokleri* buyuyordu. 🌱\n\n"
        "Senin bugun cozdugun her soru, o koklerin bir parcasi. "
        "Netler hemen firlamayabilir ama *beynin yeni sinaptik baglar kuruyor*.\n\n"
        "Simdi sana bir sey onerebilir miyim?\n\n"
        "Sadece *5 dakika* — evet sadece 5 dakika — en sevdigin derse bak. "
        "Zeigarnik Etkisi denen bilimsel bir gercek var: _Beyin baslanan isi bitirmek ister._ "
        "O 5 dakika, 30 dakikaya donusecek.\n\n"
        "_Hangi dersi en cok seviyorsun? Oradan baslayalim._ 🎯"
    ),
    (
        "Hey {name}, yorgun hissetmen cok normal. 💙\n\n"
        "Ama Stanford Universitesi'nden *Carol Dweck*'in soyledigi bir sey var:\n\n"
        "> _\"Zeka sabit degildir. Beyin bir kas gibi — calistikca guclenir.\"_\n\n"
        "Bugunku yorgunlugun, *beyninin buyudugunu* gosteriyor. "
        "Deneme netlerin dusmus olabilir ama bu bir *tanis araci*, "
        "senin zeka olcutun degil.\n\n"
        "Birlikte su hafta neye odaklanacagimizi planlayalim mi? "
        "Kucuk hedeflerle baslayalim — *her gun sadece 1 konu*.\n\n"
        "_Hangi dersle baslamak istersin?_ 🎯"
    ),
]


# ═══════════════════════════════════════════════════════════════════
# CIKMIS SORU MENU — Ders bazli interaktif katalog
# ═══════════════════════════════════════════════════════════════════

async def get_cikmis_soru_menu(ders: str, name: str = "") -> str:
    """Ders bazli cikmis soru katalogu — DB'den dinamik, WP gorsel kalitede."""
    import re
    from db_pool import db_fetch
    first = name.split()[0] if name else ""

    # Ders normalizasyonu
    _NORM = {'türkçe':'Turkce', 'turkce':'Turkce', 'fizik':'Fizik', 'matematik':'Matematik',
             'kimya':'Kimya', 'biyoloji':'Biyoloji', 'tarih':'Tarih', 'edebiyat':'Edebiyat',
             'coğrafya':'Cografya', 'cografya':'Cografya', 'felsefe':'Felsefe', 'geometri':'Geometri'}
    ders_norm = _NORM.get(ders.lower().strip(), ders)

    EMOJI = {'Fizik':'⚡', 'Matematik':'📐', 'Kimya':'🧪', 'Biyoloji':'🧬',
             'Turkce':'📝', 'Tarih':'🏛', 'Edebiyat':'📚', 'Cografya':'🌍', 'Felsefe':'🧠', 'Geometri':'📐'}
    ders_emoji = EMOJI.get(ders_norm, '📊')

    rows = await db_fetch('''
        SELECT konu, kaynak, icerik FROM rag_content
        WHERE kaynak LIKE '%OGM Vision%' AND ders = $1
    ''', ders_norm)

    if not rows:
        return f"{first}, {ders_norm} dersinden henuz cikmis soru bankamizda kayit yok."

    # konu -> {yil-sinav -> [{soru_no, kaynak}]}
    catalog = {}
    for r in rows:
        konu = r['konu']
        matches = re.findall(r'SORU\s+(\d+)\s*\|\s*(\d{4})[-\u2013](AYT|TYT)', r['icerik'])
        for sno, yil, sinav in matches:
            catalog.setdefault(konu, {})
            key = f'{yil}-{sinav}'
            catalog[konu].setdefault(key, []).append(int(sno))

    # Konu sirala (soru sayisina gore)
    sorted_konular = sorted(catalog.items(), key=lambda x: sum(len(v) for v in x[1].values()), reverse=True)

    # Filtrelenmis konu listesi
    filtered = []
    BAD_NAMES = ['buna göre', 'aşağıdaki', 'bu parça', 'hangisi', 'belirtilmemiş',
                 'fizik', 'kimya', 'biyoloji', 'matematik', 'cikmis soru', 'genel']
    for konu, yillar in sorted_konular:
        toplam = sum(len(v) for v in yillar.values())
        if toplam < 2:
            continue
        if any(bad in konu.lower() for bad in BAD_NAMES) and len(konu) < 15:
            continue
        filtered.append((konu, yillar, toplam))

    toplam_soru = sum(t for _, _, t in filtered)
    toplam_konu = len(filtered)

    lines = [
        f"{first}, iste {ders_norm} cikmis soru bankasi {ders_emoji}\n",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"{ders_emoji} *{ders_norm.upper()} — CIKMIS SORU KATALOGU*",
        f"_{toplam_soru} soru · {toplam_konu} konu · 2018-2025_",
        "━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    for sira, (konu, yillar, toplam) in enumerate(filtered[:12], 1):
        # Unique yillar (TYT+AYT birlesik)
        unique_yillar = sorted(set(yk.split('-')[0] for yk in yillar.keys()), reverse=True)[:5]
        # TYT/AYT ayrim goster
        has_tyt = any('TYT' in yk for yk in yillar)
        has_ayt = any('AYT' in yk for yk in yillar)
        sinav_tag = ''
        if has_tyt and has_ayt:
            sinav_tag = ' (TYT+AYT)'
        elif has_ayt:
            sinav_tag = ' (AYT)'
        elif has_tyt:
            sinav_tag = ' (TYT)'

        konu_short = konu[:28] + ('...' if len(konu) > 28 else '')
        lines.append(f"*{sira}.* *{konu_short}* — {toplam} soru{sinav_tag}")
        lines.append(f"   📅 {' · '.join(unique_yillar)}")
        lines.append("")

    # Kapaniş
    lines.append("━━━━━━━━━━━━━━━━━━━━━━\n")
    lines.append(f"💡 _Bir konu sec, sana o konudan gercek YKS sorusu gondereyim!_")
    lines.append(f"_Ornegin: \"{sorted_konular[0][0][:20]} sorusu goster\" yaz_ {ders_emoji}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 25.37+ (Neo audit #5) — WEB RENDER ENRICHMENT TEMPLATES
# Web kanalında sade text yanıtları compound block ile zenginleştirme
# kalıpları. Bot bunları referans alarak otomatik renderer ekler.
# ═══════════════════════════════════════════════════════════════════════

WEB_ENRICH_TEMPLATES = {
    # Öğrenci profil göstergesi — karne + chart + radar tek kart
    "ogrenci_profil_compound": (
        '```compound\n'
        '{"title":"{ogrenci_ad} — Akademik Profil","panels":['
        '{"type":"karne","label":"Ders Netleri","data":{"konular":[]}},'
        '{"type":"chart","label":"Trend","data":{"type":"line","labels":[],"datasets":[]}},'
        '{"type":"radar","label":"Ders Dengesi","data":{"labels":[],"datasets":[]}}'
        '],"note":"Son 5 deneme + ders bazlı performans"}\n```'
    ),
    # Konu anlatımı — formula + sim + steps zinciri
    "konu_anlatim_compound": (
        '```compound\n'
        '{"title":"{konu_adi} — Tam Anlatım","panels":['
        '{"type":"formula","label":"Temel","data":{"body":"$E = mc^2$"}},'
        '{"type":"sim","label":"İnteraktif","data":{"code":"p5 kodu"}},'
        '{"type":"steps","label":"Çözüm","data":{"steps":[]}}'
        '],"note":"Formül + simülasyon + step-by-step"}\n```'
    ),
    # Karşılaştırma — compare2 (markdown tablo YASAK)
    "kiyas_compare2": (
        '```compare2\n'
        '{"title":"{kavram_a} vs {kavram_b}",'
        '"left":{"label":"{kavram_a}","summary":""},'
        '"right":{"label":"{kavram_b}","summary":""},'
        '"rows":[{"aspect":"","left":"","right":"","highlight":true}],'
        '"takeaway":""}\n```'
    ),
    # Quiz pekiştirme — multi-choice + feedback
    "konu_quiz": (
        '```quiz\n'
        '{"title":"{konu_adi} — Hızlı Test","questions":['
        '{"stem":"?","choices":["A","B","C","D"],"correct":1,"explanation":""}'
        ']}\n```'
    ),
    # Hedef/puan ilerleme — gauge + progress + timeline
    "hedef_compound": (
        '```compound\n'
        '{"title":"Hedefin Yolculuğu","panels":['
        '{"type":"gauge","label":"İlerleme","data":{"value":65,"max":100}},'
        '{"type":"progress","label":"Müfredat","data":{"items":[]}},'
        '{"type":"timeline","label":"Zaman","data":{"events":[]}}]}\n```'
    ),
    # Çalışma planı — timeline + kgraph + progress
    "plan_compound": (
        '```compound\n'
        '{"title":"Haftalık Plan","panels":['
        '{"type":"timeline","label":"Plan","data":{}},'
        '{"type":"kgraph","label":"Konular","data":{}},'
        '{"type":"progress","label":"Tamamlanma","data":{}}]}\n```'
    ),
}


def get_enrich_template(intent: str) -> str:
    """Intent'e göre web compound template'i döndür."""
    intent_to_template = {
        "kavram_aciklama": "konu_anlatim_compound",
        "deneme_analiz":   "ogrenci_profil_compound",
        "analiz_iste":     "ogrenci_profil_compound",
        "karsilastirma":   "kiyas_compare2",
        "hedef_analiz":    "hedef_compound",
        "plan_yap":        "plan_compound",
    }
    key = intent_to_template.get(intent, "")
    return WEB_ENRICH_TEMPLATES.get(key, "")
