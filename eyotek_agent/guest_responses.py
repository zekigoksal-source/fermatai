"""
Kayıtsız Numara (Guest) Hızlı Yanıtlar — Veli/Aday Sık Sorulan Sorular.

Claude ile oluşturulmuş kurumsal cevaplar. Token harcamadan anında yanıt.
Yerel LLM (Ollama) bu şablonları referans olarak kullanır.
"""
import re
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# VELİ/ADAY İLK 10 SORU — HAZIR KURUMSAL YANITLAR
# ═══════════════════════════════════════════════════════════════════

GUEST_PATTERNS = [

    # 1. Selamlama
    {
        "patterns": [r"^(merhaba|selam|iyi\s*gun|hey|meraba|slm|sa|selamun)"],
        "response": (
            "Merhaba! Ben *FermatAI*, Fermat Egitim Kurumlari'nin dijital egitim danismaniyim.\n\n"
            "Size nasil yardimci olabilirim?\n\n"
            "- Egitim programlarimiz hakkinda bilgi\n"
            "- Sinav hazirligi (YKS, LGS, SAT, IELTS)\n"
            "- Ucretsiz seviye analizi randevusu\n\n"
            "_Sizi daha iyi yonlendirebilmem icin adinizi ogrenebilir miyim?_"
        ),
    },

    # 2. Fiyat / Ücret
    {
        "patterns": [r"(fiyat|ucret|ücret|para|maliyet|ne\s*kadar|kac\s*lira|kaç\s*tl|kac\s*tl)"],
        "response": (
            "Cok guzel bir soru! Fermat VIP'de her ogrencinin programi *kisisellestirilmis* "
            "oldugu icin fiyatlarimiz da buna gore sekillenir.\n\n"
            "Dogru bilgiyi alabilmeniz icin en iyi yol, *ucretsiz on gorusme randevusu* olusturmaktir. "
            "Bu gorusmede:\n"
            "- Ogrencinin mevcut durumu degerlendirilir\n"
            "- Ihtiyaca uygun program onerisi yapilir\n"
            "- Yatirim tutari seffafca paylasılır\n\n"
            "Hemen randevu olusturmak ister misiniz?\n"
            "Tel: *+90 546 260 54 46*\n"
            "Online: fermategitimkurumlari.com/randevu"
        ),
    },

    # 3. Nerede / Adres
    {
        "patterns": [r"(nerede|adres|konum|yer|nasil\s*gel|nasıl\s*gel|yol\s*tarif|harita|lokasyon)"],
        "response": (
            "Kurumumuz *Izmir Alsancak*'in kalbinde, yurume mesafesinde!\n\n"
            "*Adres:*\nKultur Mahallesi 1375. Sokak No:4/A\nKonak/Alsancak, Izmir 35220\n\n"
            "Konak-Alsancak hattindaki okullardan yurume mesafesinde. "
            "Ogrencilerimiz okul cikisinda kolayca ulasabilir.\n\n"
            "_Bizi ziyaret etmek icin randevu olusturmak ister misiniz?_\n"
            "Tel: *+90 546 260 54 46*"
        ),
    },

    # 4. Ne yapıyorsunuz / Programlar
    {
        "patterns": [r"(ne\s*yap|program|ders|kurs|egitim|eğitim|hizmet|branş|brans|neler\s*var)"],
        "response": (
            "Fermat VIP olarak *8 kisilik butik siniflarla* kisisel egitim sunuyoruz.\n\n"
            "*Programlarimiz:*\n"
            "- *YKS Hazirlik* — TYT + AYT (1200+ saat/yil)\n"
            "- *LGS Hazirlik* — 8. sinif (1000+ saat/yil)\n"
            "- *Okula Destek* — 9, 10, 11. sinif mufredat + YKS altyapi\n"
            "- *Ozel Ders* — Birebir, ogrenciye ozel tempo\n"
            "- *Uluslararasi* — AP, SAT, IELTS, TOEFL\n"
            "- *Deneme Kulubu* — Turkiye geneli denemeler + FERMAT AI analiz\n\n"
            "_Ogrencinin sinifi ve hedefi nedir? Ona gore en uygun programi onerebilirim._"
        ),
    },

    # 5. Başarı oranı / Sonuçlar
    {
        "patterns": [r"(basari|başarı|sonuc|sonuç|yerlest|yerleşt|kazanan|derece|oran)"],
        "response": (
            "Basari rakamlarimiz bizi cok gururlandiriyor:\n\n"
            "*YKS:*\n"
            "- *%84* ogrencimiz ilk 3 tercihine yerlesti\n"
            "- *%97* universite yerlestirme orani\n\n"
            "*LGS:*\n"
            "- *%88* nitelikli liseye yerlestirme\n"
            "- 25.000+ soru yillik analiz (FERMAT AI)\n\n"
            "*2024 YKS Sonuclari:*\n"
            "- Turkiye *9'uncusu* kurumumuzdan!\n"
            "- Ilk 100'de *2* ogrenci\n"
            "- Ilk 1000'de *4* ogrenci\n\n"
            "Bu rakamlarin arkasinda *8 kisilik VIP siniflar*, *FERMAT AI veri analizi* "
            "ve deneyimli ODTU mezunu kadromuz var.\n\n"
            "_Ogrencinin mevcut durumunu degerlendirmek icin ucretsiz analiz randevusu ister misiniz?_"
        ),
    },

    # 6. Sınıf mevcudu / Kaç kişi
    {
        "patterns": [r"(kac\s*kisi|kaç\s*kişi|sinif\s*mevcut|sınıf\s*mevcut|kontenjan|kalabalik|kalabalık|vip)"],
        "response": (
            "Bu cok onemli bir soru! Arastirmalar gosteriyor ki sinif mevcudu, "
            "akademik basarinin en belirleyici faktorlerinden biri.\n\n"
            "Fermat VIP'de *maksimum 8 kisilik siniflar* ile egitim veriyoruz.\n\n"
            "Bu ne demek?\n"
            "- Her ogrenci ogretmenine *her an* soru sorabilir\n"
            "- Bireysel geri bildirim ve hata analizi\n"
            "- Kaybolma yok, herkes gorulur\n\n"
            "_John Hattie'nin 800+ meta-analiz iceren arastirmasina gore, "
            "bireysel geri bildirim akademik basarida en yuksek etkiye sahip faktordur._\n\n"
            "Siniflarimizi gormek ister misiniz? Randevu: *+90 546 260 54 46*"
        ),
    },

    # 7. YKS / Üniversite hazırlık
    {
        "patterns": [r"(yks|tyt|ayt|universite|üniversite|uni|sinav\s*hazirlik|sınav\s*hazırlık)"],
        "response": (
            "YKS hazirligi, sadece ders calismak degil — *stratejik bir yolculuk*.\n\n"
            "Fermat VIP YKS programinda:\n"
            "- *1200+* saat yillik egitim\n"
            "- *FERMAT AI* ile deneme analizi (her hatanin kok nedeni tespit edilir)\n"
            "- Turkiye geneli deneme kulubu\n"
            "- Sinirsiz birebir takviye\n"
            "- Profesyonel kocluk ve PDR destegi\n"
            "- Baykus Kutuphane (aksam 22:00'ye kadar)\n\n"
            "_Biliyor muydunuz? Nobel odullu kronobiyolog Jeffrey Hall'a gore, "
            "beyin 90 dakikalik odak pencerelerinde en verimli calisir. "
            "Biz de programimizi bu bilimsel verilere gore kurguladik._\n\n"
            "Ogrencinin sinifi ve hedef bolumu nedir?"
        ),
    },

    # 8. LGS hazırlık
    {
        "patterns": [r"(lgs|8\.?\s*sinif|sekizinci|liselere\s*gecis|liselere\s*geçiş)"],
        "response": (
            "LGS hazirligi icin Fermat VIP'de *butik ve odakli* bir program sunuyoruz.\n\n"
            "*LGS Programi:*\n"
            "- *1000+* saat yillik egitim\n"
            "- Yeni nesil mantik-muhakeme sorusu teknikleri\n"
            "- *%88* nitelikli liseye yerlestirme orani\n"
            "- FERMAT AI ile konu bazli eksik tespiti\n"
            "- LGS mentorluk ve tercih danismanligi\n\n"
            "_Arastirmalar gosteriyor ki 'aralikli tekrar' yontemi, bilgiyi uzun sureli "
            "bellege aktarmada en etkili yontem (Spitzer, 1939). LGS programimiz bu prensibe dayanir._\n\n"
            "Cocugunuzun LGS'ye ne kadar suresi var? Birlikte degerlendirelim."
        ),
    },

    # 9. Özel ders
    {
        "patterns": [r"(ozel\s*ders|özel\s*ders|birebir|bire\s*bir|takviye)"],
        "response": (
            "Fermat VIP'de *sinirsiz birebir takviye* sistemi ile calisiyoruz!\n\n"
            "Yani anlasilmayan tek bir konu bile kalmiyor. "
            "Kurs ogrencilerimiz, takildiklari her noktada uzman ogretmenlerimizden "
            "kurumsal guvenceyle birebir destek aliyor.\n\n"
            "Ayrica kurs disinda sadece *ozel ders* almak isteyenler icin de "
            "15+ farkli bransta esnek planlama sunuyoruz.\n\n"
            "_Hangi ders veya konuda desteğe ihtiyac var? Size en uygun formulu birlikte bulalim._"
        ),
    },

    # 10. Telefon / İletişim
    {
        "patterns": [r"(telefon|numara|iletisim|iletişim|ara|ulaş|ulas|whatsapp|wp)"],
        "response": (
            "*Iletisim Bilgilerimiz:*\n\n"
            "Tel: *+90 546 260 54 46*\n"
            "Adres: Kultur Mah. 1375. Sok. No:4/A, Konak/Alsancak, Izmir\n"
            "Web: fermategitimkurumlari.com\n"
            "Randevu: fermategitimkurumlari.com/randevu\n\n"
            "Calisma saatleri: *Pazartesi-Pazar 08:00-22:00*\n\n"
            "_Hemen telefonla gorusmek ister misiniz, yoksa online randevu mu tercih edersiniz?_"
        ),
    },

    # 11. Yapay zeka / FERMAT AI
    {
        "patterns": [r"(yapay\s*zeka|ai|fermat\s*ai|teknoloji|dijital|robot)"],
        "response": (
            "Cok guzel bir konuya degindiniz! *FERMAT AI*, kurumumuzun gururu olan "
            "yapay zeka destekli egitim platformu.\n\n"
            "Ne yapar?\n"
            "- Her deneme sinavini *konu, kazanim ve hata tipi* bazinda analiz eder\n"
            "- Ogrencinin zayif noktalarini aninda tespit eder\n"
            "- Kisisellestirilmis calisma plani olusturur\n"
            "- 7/24 soru cozum destegi\n\n"
            "_Carnegie Mellon Universitesi'nin arastirmasina gore, bilissel ogretmen "
            "sistemleri (Intelligent Tutoring Systems) ogrenci basarisini ortalama 1.0 "
            "standart sapma oraninda artirmaktadir._\n\n"
            "FERMAT AI'yi yakindan gormek ister misiniz? Ucretsiz demo icin randevu alin!"
        ),
    },

    # 12. Kimsiniz / Hakkında
    {
        "patterns": [r"(kimsiniz|hakkinda|hakkınızda|siz\s*kim|kurum|nedir\s*fermat|fermat\s*ne)"],
        "response": (
            "*Fermat Egitim Kurumlari* — Izmir Alsancak'ta, *ODTU mezunlari* tarafindan "
            "kurulan butik egitim kurumu.\n\n"
            "Bizi farkli kilan:\n"
            "- *8 kisilik VIP siniflar* — kalabalikta kaybolma yok\n"
            "- *FERMAT AI* — yapay zeka destekli kisisel analiz\n"
            "- *Sinirsiz birebir takviye* — anlasilmayan konu kalmaz\n"
            "- *PDR destegi* — sadece akademik degil, psikolojik rehberlik\n"
            "- *Baykus Kutuphane* — aksam 22:00'ye kadar calisma ortami\n\n"
            "_'Egitim, standart bir urun degil; ogrencinin potansiyelini taniyan, "
            "ona saygi gosteren ve onu kendi en iyi versiyonuna tasiyan butuncul bir tasarimdir.'_\n\n"
            "Sizi yakindan tanimak isteriz! Randevu: *+90 546 260 54 46*"
        ),
    },
]


async def try_guest_response(message: str) -> Optional[str]:
    """Kayıtsız numara için hızlı yanıt dene. None dönerse Claude'a git."""
    msg_lower = message.lower().strip()

    for item in GUEST_PATTERNS:
        for pattern in item["patterns"]:
            if re.search(pattern, msg_lower):
                return item["response"]

    # Pattern bulunamadı — Claude'a git (ama token dikkatli kullan)
    return None
