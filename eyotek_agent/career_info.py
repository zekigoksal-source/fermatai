"""
Career Info — Meslek/Bölüm Tanıtım Kaynağı (22 Nisan 2026)
============================================================
İrem (905075530945) 21 Nisan'da "Kimya mühendisliği ne iş yapar" sordu,
Fix 1 Claude fallback yaptı ama her seferinde Claude üretiyor = token israf.

Bu modül: 50+ meslek/bölüm için önceden hazırlanmış KISA tanım +
iş alanları + puan aralığı + kaç yıl + avantaj/dezavantaj.

Claude talep ederse direkt tool'dan döner — 0 token, < 10 ms.

VERİ KAPSAMI (50 ana bölüm + türev):
  Sayısal (SAY): Tıp, Diş, Eczacılık, Mühendislikler (15), Mimarlık,
                 Bilgisayar, Yazılım, Veri Bilimi, Biyomedikal
  Eşit Ağırlık (EA): Hukuk, Psikoloji, İşletme, Ekonomi, Siyaset,
                     Uluslararası İlişkiler, Gazetecilik, Öğretmenlik
  Sözel (SÖZ): Tarih, Türk Dili, Sosyoloji, Felsefe, Arkeoloji
  Dil (DIL): Mütercim, İngilizce Öğretmen, Turizm
  Teknoloji: Siber Güvenlik, Yapay Zeka, Elektronik

Gelecek: YÖK/ÖSYS veri çek, 500+ bölüm.
"""
from __future__ import annotations


# Meslek/bölüm verileri — Claude bu veriyi kullansın
_CAREERS = {
    "kimya muhendisligi": {
        "ad": "Kimya Mühendisliği",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "350-500 (SAY)",
        "ne_yapar": (
            "Maddenin fiziksel ve kimyasal dönüşümlerini endüstriyel ölçekte "
            "tasarlayan ve yöneten mühendislik. Reaktör, destilasyon kolonu, "
            "kimyasal proses ve enerji optimizasyonu yaparlar."
        ),
        "calisma_alanlari": [
            "Petrokimya / rafineri (TÜPRAŞ, PETKİM)",
            "İlaç endüstrisi (üretim, kalite)",
            "Kozmetik / gıda endüstrisi",
            "Çevre mühendisliği (atık yönetimi)",
            "Enerji (biyogaz, yakıt hücresi)",
        ],
        "onemli_dersler": "Organik kimya, termodinamik, kütle-enerji dengesi, proses kontrol",
        "avantaj": "Geniş iş alanı, yurt dışı imkanı, Ar-Ge projeleri",
        "dezavantaj": "Laboratuvar ağırlıklı, bazı işler riskli (patlayıcı/toksik)",
        "maas_aralik": "Giriş 35-50K, 5 yıl sonra 60-100K (2026 TL)",
    },
    "bilgisayar muhendisligi": {
        "ad": "Bilgisayar Mühendisliği",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "400-560 (SAY)",
        "ne_yapar": (
            "Yazılım ve donanım sistemleri tasarlayan mühendislik. Programlama, "
            "algoritmalar, veri yapıları, yapay zeka, ağ ve siber güvenlik "
            "kapsamında çalışır."
        ),
        "calisma_alanlari": [
            "Yazılım geliştirme (Google, Amazon, yerli fintech)",
            "Yapay zeka / Veri bilimi",
            "Siber güvenlik",
            "Oyun / grafik motorları",
            "Mobil uygulama",
            "Freelance / girişim",
        ],
        "onemli_dersler": "Algoritmalar, veri yapıları, işletim sistemleri, makine öğrenmesi",
        "avantaj": "Yüksek maaş, remote çalışma, global iş imkanı, Türkiye'de çok tercih edilen",
        "dezavantaj": "Sürekli kendini güncelleme zorunluluğu, oturma süresi yorucu",
        "maas_aralik": "Giriş 40-70K, 5 yıl sonra 80-200K (yurtdışı ise $4-8K)",
    },
    "tip": {
        "ad": "Tıp Fakültesi",
        "alan": "SAY",
        "sure_yil": 6,
        "puan_aralik": "530-560 (SAY) — ilk %1",
        "ne_yapar": "İnsan sağlığını koruyan, hastalıkları teşhis ve tedavi eden meslek.",
        "calisma_alanlari": [
            "Devlet hastanesi / özel hastane / klinik",
            "Aile hekimliği",
            "Uzmanlık (cerrahi, iç hastalıkları, kadın doğum vb.)",
            "Akademisyen (öğretim üyesi)",
        ],
        "onemli_dersler": "Anatomi, fizyoloji, biyokimya, farmakoloji, klinik stajlar",
        "avantaj": "Saygın meslek, insan hayatına katkı, iş garantisi",
        "dezavantaj": "6 yıl + uzmanlık 4-6 yıl (toplam 10-12 yıl), yoğun nöbet",
        "maas_aralik": "Asistan 30-45K, uzman 60-150K, özel sektör 100-300K+",
    },
    "dis hekimligi": {
        "ad": "Diş Hekimliği",
        "alan": "SAY",
        "sure_yil": 5,
        "puan_aralik": "500-540 (SAY)",
        "ne_yapar": "Ağız, diş ve çene sağlığını koruyan/tedavi eden meslek.",
        "calisma_alanlari": ["Özel klinik (kendi muayene)", "Devlet diş hastanesi", "ADSM", "Ortodonti/implant uzmanlık"],
        "onemli_dersler": "Anatomi, protez, ortodonti, periodontoloji",
        "avantaj": "Kendi muayene açma imkanı, serbest çalışma",
        "dezavantaj": "El becerisi önemli, ergonomik zorluk (sırt/boyun)",
        "maas_aralik": "Başlangıç 40-60K, deneyimli 80-200K",
    },
    "mimarlik": {
        "ad": "Mimarlık",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "280-420 (SAY)",
        "ne_yapar": "Bina, yapı ve mekanları tasarlayan, estetik+işlevsel birleştiren meslek.",
        "calisma_alanlari": ["Mimari büro", "İnşaat şirketi", "Kamu (belediye, TOKİ)", "Restorasyon", "İç mimarlık"],
        "onemli_dersler": "Mimari tasarım, yapı bilgisi, statik, Autocad/Revit, tarihî yapılar",
        "avantaj": "Yaratıcılık, şehircilik, sanat+bilim birleşimi",
        "dezavantaj": "Proje yoğun, yoğun gece mesaisi, iş bulmak zor olabilir",
        "maas_aralik": "Giriş 30-50K, deneyimli 70-150K, ortak 200K+",
    },
    "hukuk": {
        "ad": "Hukuk",
        "alan": "EA",
        "sure_yil": 4,
        "puan_aralik": "380-520 (EA)",
        "ne_yapar": "Hukuk sistemini yorumlayan, savunan, adaleti tesis eden meslek.",
        "calisma_alanlari": ["Avukatlık (serbest)", "Hakim/savcı (KPSS)", "Kurumsal hukuk (şirket içi)", "Noter"],
        "onemli_dersler": "Anayasa, medeni hukuk, ceza hukuku, ticaret hukuku, idare hukuku",
        "avantaj": "Serbest çalışma, saygın meslek, geniş alan",
        "dezavantaj": "Mesleğe başlama sınavı (avukatlık stajı), yoğun mevzuat takibi",
        "maas_aralik": "Stajyer 25K, avukat 40-100K, tecrübeli 150K+",
    },
    "psikoloji": {
        "ad": "Psikoloji",
        "alan": "EA",
        "sure_yil": 4,
        "puan_aralik": "350-480 (EA)",
        "ne_yapar": "İnsan davranışı, zihin ve duygularını bilimsel inceleyen + terapi yapan meslek.",
        "calisma_alanlari": ["Klinik psikoloji (yüksek lisans sonrası)", "Okul psikolojik danışmanlığı", "Endüstri/örgüt psikolojisi", "Araştırma/akademi"],
        "onemli_dersler": "Bilişsel psikoloji, gelişim, anormal, istatistik, terapi yaklaşımları",
        "avantaj": "İnsanla çalışma, anlamlı iş, yüksek lisans ile uzmanlık imkanı",
        "dezavantaj": "Lisansta düşük maaş, klinik olmak için yüksek lisans şart",
        "maas_aralik": "Lisans 20-35K, klinik psk 50-100K, özel muayene 100-300K+",
    },
    "makine muhendisligi": {
        "ad": "Makine Mühendisliği",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "300-480 (SAY)",
        "ne_yapar": "Mekanik sistemler, makineler, motor, üretim hattı tasarlayan mühendislik.",
        "calisma_alanlari": ["Otomotiv (TOGG, Ford, Mercedes)", "Savunma sanayi (ASELSAN, TAI)", "Havacılık", "Enerji"],
        "onemli_dersler": "Statik, dinamik, termodinamik, akışkanlar, makine elemanları, CAD",
        "avantaj": "Geniş iş alanı, savunma/havacılık devlet projeleri",
        "dezavantaj": "Şantiye/fabrika ortamı, sürekli kendini geliştirme",
        "maas_aralik": "Giriş 30-45K, 5 yıl 55-90K, yönetici 120K+",
    },
    "elektrik elektronik": {
        "ad": "Elektrik-Elektronik Mühendisliği",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "350-500 (SAY)",
        "ne_yapar": "Elektrik enerjisi üretim/dağıtımı + elektronik devre tasarımı yapan mühendislik.",
        "calisma_alanlari": ["TEİAŞ/TEDAŞ", "Enerji üretim şirketleri", "Elektronik tasarım", "Savunma (radar, haberleşme)"],
        "onemli_dersler": "Devre analizi, elektromanyetik, dijital sistemler, güç sistemleri, mikroişlemci",
        "avantaj": "Geniş alan, ülke için kritik sektör, yurt dışı imkanı",
        "dezavantaj": "Matematik/fizik ağır, dış mekan/şantiye çalışması",
        "maas_aralik": "Giriş 32-50K, 5 yıl 60-100K",
    },
    "endustri muhendisligi": {
        "ad": "Endüstri Mühendisliği",
        "alan": "SAY",
        "sure_yil": 4,
        "puan_aralik": "350-500 (SAY)",
        "ne_yapar": "Üretim sistemlerini optimize eden, verimlilik ve kalite yöneten mühendislik.",
        "calisma_alanlari": ["Üretim (fabrika, lojistik)", "Danışmanlık (PwC, Accenture)", "Finans (bankacılık)", "Operasyon yönetimi"],
        "onemli_dersler": "Yöneylem araştırması, optimizasyon, istatistik, kalite yönetimi, ERP",
        "avantaj": "Her sektörde iş, yönetime geçiş kolay, finans da açık",
        "dezavantaj": "Teknik mühendislik değil, 'neyin mühendisi?' algısı",
        "maas_aralik": "Giriş 35-55K, 5 yıl 60-110K, yönetici 150K+",
    },
    "eczacilik": {
        "ad": "Eczacılık",
        "alan": "SAY",
        "sure_yil": 5,
        "puan_aralik": "480-530 (SAY)",
        "ne_yapar": "İlaç üretimi, dağıtımı, hasta danışmanlığı yapan meslek.",
        "calisma_alanlari": ["Eczane (kendi/zincir)", "İlaç firması (Pfizer, Sanofi, yerli)", "Hastane eczanesi", "Ruhsatlandırma"],
        "onemli_dersler": "Farmakoloji, farmakognozi, kimya, eczacılık teknolojisi",
        "avantaj": "Kendi eczane açma, stabil gelir, klinik+firma seçeneği",
        "dezavantaj": "Eczane açmak maliyetli, 5 yıl uzun",
        "maas_aralik": "Kalfa 35-50K, eczacı 60-150K, kendi eczane daha yüksek",
    },
    "isletme": {
        "ad": "İşletme",
        "alan": "EA",
        "sure_yil": 4,
        "puan_aralik": "250-400 (EA)",
        "ne_yapar": "İşletme yönetimi, finans, pazarlama, insan kaynakları alanlarında çalışma.",
        "calisma_alanlari": ["Bankacılık", "Pazarlama", "İK", "Danışmanlık", "Girişim"],
        "onemli_dersler": "Muhasebe, finans, pazarlama, ekonomi, yönetim",
        "avantaj": "Geniş alan, girişim imkanı, her sektörde iş",
        "dezavantaj": "Rekabet yüksek, bölüm yaygın (diploma tek başına yetmez)",
        "maas_aralik": "Giriş 25-40K, 5 yıl 45-80K",
    },
    "mutercim tercuman": {
        "ad": "Mütercim-Tercümanlık",
        "alan": "DIL",
        "sure_yil": 4,
        "puan_aralik": "280-440 (DIL)",
        "ne_yapar": "İngilizce (veya başka dil) yazılı/sözlü çeviri, simültane çeviri yapar.",
        "calisma_alanlari": ["Serbest çeviri", "Kurumsal (Bakanlık, BM)", "Kitap editörlüğü", "Turizm"],
        "onemli_dersler": "İleri İngilizce, çeviribilim, özel alan terimleri (hukuk/tıp)",
        "avantaj": "Serbest çalışma, yurt dışı imkanı, uzaktan çalışma",
        "dezavantaj": "Sürekli iş bulma kaygısı, AI çevirisi rekabeti",
        "maas_aralik": "Serbest 30-80K (değişken), kadrolu 40-70K",
    },

    # ═══════════════ 23 Nisan genişleme: 13 → 50+ meslek ═══════════════

    # SAY — Sağlık bilimleri
    "veteriner": {
        "ad": "Veteriner Hekimliği", "alan": "SAY", "sure_yil": 5,
        "puan_aralik": "430-500 (SAY)",
        "ne_yapar": "Hayvan sağlığını koruyan/tedavi eden, gıda güvenliği denetleyen meslek.",
        "calisma_alanlari": ["Klinik veterinerlik", "Tarım/Gıda Bakanlığı", "Hayvanat bahçesi", "Akademi"],
        "onemli_dersler": "Anatomi, farmakoloji, cerrahi, mikrobiyoloji",
        "avantaj": "Kendi klinik açma, hayvan sevenler için ideal",
        "dezavantaj": "Kırsal alanda fizik zorluk, beklenenden düşük maaş",
        "maas_aralik": "Klinik 30-50K, kendi 60-150K",
    },
    "fizyoterapi": {
        "ad": "Fizyoterapi ve Rehabilitasyon", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "350-460 (SAY)",
        "ne_yapar": "Kas-iskelet sistemini, nörolojik problemleri hareket terapisi ile tedavi eder.",
        "calisma_alanlari": ["Hastane", "Özel rehabilitasyon merkezi", "Sporcu sağlığı", "Ev bakımı"],
        "onemli_dersler": "Anatomi, kinezyoloji, nörofizyoloji, manipülatif terapi",
        "avantaj": "İnsan-odaklı iş, spor kulüpleri iş imkanı, kendi pratik",
        "dezavantaj": "Fiziksel yorgunluk, uzun ayakta durma",
        "maas_aralik": "Giriş 28-42K, kendi pratik 60-120K",
    },
    "hemsirelik": {
        "ad": "Hemşirelik", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "270-420 (SAY)",
        "ne_yapar": "Hasta bakımı, tedavi uygulama, sağlık eğitimi yapar.",
        "calisma_alanlari": ["Hastane (her bölüm)", "Aile hekimliği", "Okul sağlığı", "Yurt dışı"],
        "onemli_dersler": "Anatomi, farmakoloji, hasta bakımı, acil",
        "avantaj": "İş garantisi, yurt dışı talep yüksek, KPSS atama",
        "dezavantaj": "Nöbet, fiziksel/duygusal zorluk",
        "maas_aralik": "Giriş 28-38K, deneyimli 45-75K",
    },
    "beslenme": {
        "ad": "Beslenme ve Diyetetik", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "340-440 (SAY)",
        "ne_yapar": "Bireysel/toplumsal beslenme, diyet planı, klinik beslenme.",
        "calisma_alanlari": ["Hastane diyetisyeni", "Özel muayene", "Spor kulübü", "Gıda firması"],
        "onemli_dersler": "Biyokimya, beslenme, fizyoloji, sağlık",
        "avantaj": "Popüler alan, kendi muayene, sosyal medya görünürlük",
        "dezavantaj": "Piyasa dolu, diploma yetmiyor (sertifikalar önemli)",
        "maas_aralik": "Giriş 25-40K, kendi 50-150K+",
    },
    "ebelik": {
        "ad": "Ebelik", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "290-380 (SAY)",
        "ne_yapar": "Gebelik, doğum, lohusa ve bebek bakımı.",
        "calisma_alanlari": ["Hastane doğum", "Aile sağlığı merkezi", "Özel klinik"],
        "onemli_dersler": "Kadın-doğum, pediatri, gebelik takibi",
        "avantaj": "KPSS atama, istikrarlı meslek",
        "dezavantaj": "Nöbet, duygusal yük",
        "maas_aralik": "Giriş 28-38K, deneyimli 42-65K",
    },

    # SAY — Diğer mühendislikler
    "insaat muhendisligi": {
        "ad": "İnşaat Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "280-450 (SAY)",
        "ne_yapar": "Binalar, köprüler, yollar, barajlar — tasarım + uygulama.",
        "calisma_alanlari": ["Müteahhitlik", "Kamu (Karayolları, DSİ)", "Şantiye", "Statik proje büroları"],
        "onemli_dersler": "Statik, dinamik, beton, çelik, zemin mekaniği",
        "avantaj": "Geniş iş alanı, yurt dışı projeleri, yönetime geçiş",
        "dezavantaj": "Şantiye zor, sektör dalgalı",
        "maas_aralik": "Giriş 28-45K, 5 yıl 60-100K, yurt dışı $3-6K",
    },
    "harita muhendisligi": {
        "ad": "Harita Mühendisliği (Geomatik)", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "270-360 (SAY)",
        "ne_yapar": "Arazi ölçümü, kadastro, harita üretimi, GIS uygulamaları.",
        "calisma_alanlari": ["Tapu-Kadastro", "Belediye imar", "Mühendislik büroları", "GIS firmaları"],
        "onemli_dersler": "Matematik, fotogrametri, GIS, kartografya, GNSS",
        "avantaj": "Uzmanlık alanı, devlet atama imkanı",
        "dezavantaj": "Alan çalışması, hava koşulları",
        "maas_aralik": "Giriş 28-42K, 5 yıl 50-80K",
    },
    "cevre muhendisligi": {
        "ad": "Çevre Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "260-380 (SAY)",
        "ne_yapar": "Su, atık, hava kirliliği kontrolü, çevresel etki değerlendirmesi.",
        "calisma_alanlari": ["Belediye", "Çevre Bakanlığı", "Su/atık arıtma firmaları", "ÇED danışmanlık"],
        "onemli_dersler": "Kimya, hidrolik, mikrobiyoloji, atık yönetimi",
        "avantaj": "Yeşil dönüşüm talebi artıyor, danışmanlık imkanı",
        "dezavantaj": "Saha çalışması, bazen tehlikeli ortamlar",
        "maas_aralik": "Giriş 28-42K, deneyimli 50-90K",
    },
    "gida muhendisligi": {
        "ad": "Gıda Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "280-430 (SAY)",
        "ne_yapar": "Gıda üretimi, kalite kontrol, yeni ürün geliştirme.",
        "calisma_alanlari": ["Gıda firmaları (ETİ, Ülker)", "Süt/et/un endüstrisi", "Kalite labaratuvarları", "Gıda kontrol"],
        "onemli_dersler": "Gıda biyokimyası, mikrobiyoloji, işleme teknolojisi",
        "avantaj": "Her zaman talep var, Ar-Ge projeleri",
        "dezavantaj": "Üretim tesisi/vardiya, soğuk zincir",
        "maas_aralik": "Giriş 30-45K, 5 yıl 55-90K",
    },
    "bilisim sistemleri": {
        "ad": "Bilişim Sistemleri Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "330-460 (SAY)",
        "ne_yapar": "Bilişim altyapısı, ağ, sistem entegrasyonu, kurumsal yazılım.",
        "calisma_alanlari": ["Bankalar", "Telekom", "Kurumsal BT", "ERP firmaları (SAP)"],
        "onemli_dersler": "Ağ, veritabanı, sistem analizi, ERP, SQL",
        "avantaj": "Bilgisayar mühendisliğine alternatif, finans sektörü talebi",
        "dezavantaj": "Saf yazılım değil hibrit — dönüşüm gerekebilir",
        "maas_aralik": "Giriş 38-60K, 5 yıl 75-130K",
    },
    "yapay zeka muhendisligi": {
        "ad": "Yapay Zeka Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "450-555 (SAY)",
        "ne_yapar": "Makine öğrenmesi, derin öğrenme, AI sistemleri geliştirme.",
        "calisma_alanlari": ["OpenAI/Anthropic tarzı firmalar", "Yerli AI girişimleri", "Savunma (ASELSAN AI)", "Araştırma"],
        "onemli_dersler": "Doğrusal cebir, istatistik, makine öğrenmesi, Python, NLP",
        "avantaj": "YÜKSEK maaş, global talep, geleceğin mesleği",
        "dezavantaj": "Matematik ağır, sürekli yeni teknoloji",
        "maas_aralik": "Giriş 60-100K, 5 yıl 150-300K (yurtdışı $8-15K)",
    },
    "siber guvenlik": {
        "ad": "Siber Güvenlik Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "400-510 (SAY)",
        "ne_yapar": "Sistem güvenliği, saldırı tespit, ağ koruma, pentest.",
        "calisma_alanlari": ["Bankalar", "BTK", "TÜBİTAK", "Pentest firmaları", "Red/Blue Team"],
        "onemli_dersler": "Ağ güvenliği, kriptografi, etik hackleme, OSCP",
        "avantaj": "Uzmanlık yüksek, yurt dışı talep, sertifikalar değerli",
        "dezavantaj": "Sürekli tehdit takibi, gece çağrıları",
        "maas_aralik": "Giriş 50-80K, uzman 120-250K",
    },
    "biyomedikal": {
        "ad": "Biyomedikal Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "340-450 (SAY)",
        "ne_yapar": "Tıbbi cihaz tasarımı, bakım, hastane teknolojileri.",
        "calisma_alanlari": ["Hastane biyomedikal", "Cihaz firmaları (Siemens, GE)", "Ar-Ge"],
        "onemli_dersler": "Anatomi, elektronik, görüntüleme, biyomekanik",
        "avantaj": "Sağlık + teknoloji birleşimi, yurt dışı imkanı",
        "dezavantaj": "Türkiye'de talep az, genelde ithal cihaz bakım",
        "maas_aralik": "Giriş 32-48K, 5 yıl 55-95K",
    },
    "havacilik muhendisligi": {
        "ad": "Havacılık/Uzay Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "430-530 (SAY)",
        "ne_yapar": "Uçak/uydu tasarımı, aerodinamik, itki sistemleri.",
        "calisma_alanlari": ["TUSAŞ/TAI", "Roketsan", "ASELSAN", "THY teknik", "NASA/ESA stajları"],
        "onemli_dersler": "Aerodinamik, termodinamik, uçuş mekaniği, kompozit",
        "avantaj": "Prestijli, savunma projeleri (MİLGEM, KAAN), Ar-Ge",
        "dezavantaj": "Dar alan, iş yerleri sınırlı (Ankara ağırlıklı)",
        "maas_aralik": "Giriş 40-65K, 5 yıl 75-130K",
    },
    "gemi insaati": {
        "ad": "Gemi İnşaatı ve Gemi Makinaları", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "250-350 (SAY)",
        "ne_yapar": "Gemi tasarımı, tersane üretimi, deniz teknolojileri.",
        "calisma_alanlari": ["Tersaneler (Tuzla)", "Deniz Kuvvetleri", "MİLGEM", "Savunma"],
        "onemli_dersler": "Akışkanlar, statik, mukavemet, gemi hidrodinamiği",
        "avantaj": "Türkiye gemi ihracatçısı, savunma projeleri",
        "dezavantaj": "Dar iş alanı, sahil kentleri",
        "maas_aralik": "Giriş 35-50K, deneyimli 60-100K",
    },
    "metalurji": {
        "ad": "Metalurji ve Malzeme Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "260-380 (SAY)",
        "ne_yapar": "Metal/seramik/polimer üretimi, alaşım, malzeme seçimi.",
        "calisma_alanlari": ["Demir-çelik (Erdemir)", "Otomotiv", "Havacılık", "Kompozit"],
        "onemli_dersler": "Kristalografi, faz diyagramları, mekanik özellikler, korozyon",
        "avantaj": "Savunma ve havacılık projeleri, Ar-Ge",
        "dezavantaj": "Fabrika ortamı, sıcaklık/toz",
        "maas_aralik": "Giriş 32-48K, deneyimli 55-100K",
    },
    "maden muhendisligi": {
        "ad": "Maden Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "220-330 (SAY)",
        "ne_yapar": "Maden arama, çıkarma, işletme, jeoteknik.",
        "calisma_alanlari": ["Maden işletmeleri", "Enerji (kömür)", "Tünel projeleri"],
        "onemli_dersler": "Jeoloji, kazı teknolojisi, madencilik güvenliği",
        "avantaj": "Maaş yüksek (şantiye primli)",
        "dezavantaj": "Tehlikeli iş ortamı, uzak lokasyon",
        "maas_aralik": "Giriş 35-55K, saha 60-120K (prim ile)",
    },
    "jeoloji": {
        "ad": "Jeoloji Mühendisliği", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "200-320 (SAY)",
        "ne_yapar": "Yer bilimleri, zemin etüdü, deprem, doğal kaynaklar.",
        "calisma_alanlari": ["AFAD", "MTA", "Belediye zemin etüdü", "Petrol arama"],
        "onemli_dersler": "Mineraloji, stratigrafi, zemin mekaniği, sismoloji",
        "avantaj": "Deprem ülkesi — öneminmli, kamu atama",
        "dezavantaj": "Arazi çalışması, ücretler düşük",
        "maas_aralik": "Giriş 25-38K, deneyimli 45-75K",
    },

    # EA — Sosyal bilimler
    "iktisat": {
        "ad": "İktisat / Ekonomi", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "290-420 (EA)",
        "ne_yapar": "Makro/mikro ekonomi analiz, politika, bankacılık.",
        "calisma_alanlari": ["Merkez Bankası", "Bankalar", "Araştırma şirketleri", "Kamu kurumları (KPSS)"],
        "onemli_dersler": "Mikro, makro, ekonometri, finansal ekonomi",
        "avantaj": "Geniş analitik alan, doktora ile akademi",
        "dezavantaj": "Teori ağırlıklı, iş için ek beceri gerek",
        "maas_aralik": "Giriş 28-45K, deneyimli 55-100K",
    },
    "uluslararasi iliskiler": {
        "ad": "Uluslararası İlişkiler", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "290-420 (EA)",
        "ne_yapar": "Diplomasi, uluslararası politika, uluslararası kurumlar.",
        "calisma_alanlari": ["Dışişleri Bakanlığı", "BM/AB ofisleri", "Düşünce kuruluşları", "Gazetecilik"],
        "onemli_dersler": "Siyaset bilimi, uluslararası hukuk, yabancı dil, tarih",
        "avantaj": "Dışişleri KPSS sınavı, yurt dışı staj",
        "dezavantaj": "Rekabet çok, dil 2+ gerekli (İng + Fransızca/Arapça)",
        "maas_aralik": "Giriş 30-55K, Dışişleri 60-150K",
    },
    "siyaset bilimi": {
        "ad": "Siyaset Bilimi ve Kamu Yönetimi", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "260-400 (EA)",
        "ne_yapar": "Kamu yönetimi, siyaset teorisi, bürokrasi, yerel yönetim.",
        "calisma_alanlari": ["Kaymakamlık (KPSS)", "Belediye", "Bakanlıklar", "NGO'lar"],
        "onemli_dersler": "Siyaset felsefesi, kamu yönetimi, hukuk, istatistik",
        "avantaj": "KPSS ile geniş kamu atama imkanı",
        "dezavantaj": "Özel sektör az, siyaset kaygan zemin",
        "maas_aralik": "Giriş 28-42K, kaymakam 55-85K",
    },
    "gazetecilik": {
        "ad": "Gazetecilik / Medya", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "230-380 (EA/SÖZ)",
        "ne_yapar": "Haber toplama, yazma, sunma, dijital medya.",
        "calisma_alanlari": ["Gazeteler", "TV", "Online medya", "Halkla ilişkiler", "Sosyal medya ajansları"],
        "onemli_dersler": "Haber yazımı, medya etiği, video prodüksiyon",
        "avantaj": "Yaratıcı, sosyal medya çağında talep",
        "dezavantaj": "Düşük giriş maaşı, baskı ortamı, freelance yoğun",
        "maas_aralik": "Giriş 22-38K, deneyimli 45-90K",
    },

    # EA — Eğitim
    "sinif ogretmenligi": {
        "ad": "Sınıf Öğretmenliği", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "250-400 (EA)",
        "ne_yapar": "İlkokul 1-4. sınıf temel eğitim, tüm derslerden.",
        "calisma_alanlari": ["Devlet okulu (KPSS+ÖABT)", "Özel okul", "Kolej"],
        "onemli_dersler": "Eğitim bilimi, okuma-yazma öğretimi, çocuk gelişimi",
        "avantaj": "Çocuklarla çalışma, tatil uzun, KPSS atama",
        "dezavantaj": "Atama kontenjanları düşük, özel okul maaşı düşük",
        "maas_aralik": "Atama 25-38K, özel okul 22-50K",
    },
    "matematik ogretmenligi": {
        "ad": "Matematik Öğretmenliği", "alan": "SAY/EA", "sure_yil": 4,
        "puan_aralik": "300-440 (SAY veya EA)",
        "ne_yapar": "Ortaokul/lise matematik öğretmeni.",
        "calisma_alanlari": ["Devlet okulu (KPSS+ÖABT)", "Özel okul", "Özel ders", "Dershane/kurs"],
        "onemli_dersler": "Cebir, analiz, pedagoji, ÖABT matematik",
        "avantaj": "Atama yok ise özel ders iyi kazandırır",
        "dezavantaj": "Atama çok düşük kontenjan, rekabet",
        "maas_aralik": "Atama 28-42K, özel ders 50-150K",
    },

    # SÖZ — Sözel alanlar
    "psikolojik danismanlik": {
        "ad": "Psikolojik Danışmanlık ve Rehberlik (PDR)", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "320-440 (EA)",
        "ne_yapar": "Okul rehberlik, aile danışmanlığı, mesleki yönlendirme.",
        "calisma_alanlari": ["Okul PDR", "Rehberlik araştırma merkezi", "Aile danışmanlık", "Özel muayene"],
        "onemli_dersler": "Gelişim, rehberlik teknikleri, test yöntemleri",
        "avantaj": "Psikolojiye yakın, KPSS atama, öğrenci ile çalışma",
        "dezavantaj": "Klinik değil (terapi hakkı yok), atama kota",
        "maas_aralik": "Atama 28-42K, özel muayene 50-120K",
    },
    "sosyoloji": {
        "ad": "Sosyoloji", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "230-360 (EA/SÖZ)",
        "ne_yapar": "Toplum yapısı, sosyal olgular, araştırma.",
        "calisma_alanlari": ["Araştırma şirketleri", "STK'lar", "Kamu (aile/sosyal hizmet)", "Gazetecilik"],
        "onemli_dersler": "Sosyoloji teorisi, istatistik, araştırma yöntemi",
        "avantaj": "Analitik düşünce, doktora ile akademi",
        "dezavantaj": "Dar iş alanı, piyasa değeri belirsiz",
        "maas_aralik": "Giriş 22-38K, araştırmacı 40-75K",
    },
    "arkeoloji": {
        "ad": "Arkeoloji", "alan": "SÖZ", "sure_yil": 4,
        "puan_aralik": "200-340 (SÖZ)",
        "ne_yapar": "Tarihi eserlerin araştırılması, kazı, müze.",
        "calisma_alanlari": ["Müze", "Kültür Bakanlığı", "Kazı ekipleri", "Akademi"],
        "onemli_dersler": "Antikçağ, arkeoloji yöntemleri, Latince/Yunanca",
        "avantaj": "Tutku mesleği, yurt dışı staj, müze",
        "dezavantaj": "İş imkanı az, kazılarda zor koşullar, düşük maaş",
        "maas_aralik": "Giriş 22-35K, deneyimli 38-60K",
    },
    "felsefe": {
        "ad": "Felsefe", "alan": "EA/SÖZ", "sure_yil": 4,
        "puan_aralik": "220-370 (EA/SÖZ)",
        "ne_yapar": "Düşünce tarihi, etik, bilim felsefesi.",
        "calisma_alanlari": ["Öğretmenlik (ÖABT)", "Akademi", "Yayıncılık", "İçerik üretimi"],
        "onemli_dersler": "Mantık, epistemoloji, etik, çağdaş felsefe",
        "avantaj": "Analitik düşünce, yazarlık, akademi yolu",
        "dezavantaj": "İş azlığı, ek formasyon gerek",
        "maas_aralik": "Öğretmen 30-45K, akademi 40-80K",
    },
    "tarih": {
        "ad": "Tarih", "alan": "SÖZ", "sure_yil": 4,
        "puan_aralik": "210-370 (SÖZ)",
        "ne_yapar": "Tarihi araştırma, belge analizi, öğretmenlik.",
        "calisma_alanlari": ["Öğretmenlik (ÖABT)", "Müze", "Arşiv", "Akademi"],
        "onemli_dersler": "Osmanlı tarihi, Türkiye Cumhuriyeti, çağdaş tarih, diplomatika",
        "avantaj": "Çok çeşitli alt alanlar (Osmanlı, Bizans, askeri)",
        "dezavantaj": "Öğretmenlik dışı iş az, akademi rekabetli",
        "maas_aralik": "Öğretmen 28-42K, akademi 40-80K",
    },
    "turk dili edebiyati": {
        "ad": "Türk Dili ve Edebiyatı", "alan": "SÖZ", "sure_yil": 4,
        "puan_aralik": "280-410 (SÖZ/EA)",
        "ne_yapar": "Edebiyat, dil bilimi, şiir/roman incelemesi.",
        "calisma_alanlari": ["Öğretmenlik (ÖABT)", "Yayıncılık editörlük", "Akademi", "Sinema/TV senaryo"],
        "onemli_dersler": "Eski edebiyat, yeni edebiyat, halk edebiyatı, dil bilimi",
        "avantaj": "Geniş kültür + yaratıcı yazarlık fırsatı",
        "dezavantaj": "Öğretmenlik kontenjanı az",
        "maas_aralik": "Öğretmen 28-45K, editör 35-65K",
    },

    # DIL
    "ingiliz dili edebiyati": {
        "ad": "İngiliz Dili ve Edebiyatı", "alan": "DIL", "sure_yil": 4,
        "puan_aralik": "280-450 (DIL)",
        "ne_yapar": "İngilizce edebiyat, çeviri, dilbilim.",
        "calisma_alanlari": ["İngilizce öğretmenliği", "Özel ders", "Turizm", "Çeviri"],
        "onemli_dersler": "İngiliz edebiyatı (Shakespeare, Romantikler), dilbilim",
        "avantaj": "İngilizce mesleği, özel ders kazancı iyi",
        "dezavantaj": "Öğretmenlik atama zor",
        "maas_aralik": "Öğretmen 28-45K, özel ders 60-150K",
    },

    # Yeni teknoloji alanları
    "uzay muhendisligi": {
        "ad": "Uzay Bilimleri ve Teknolojileri", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "400-520 (SAY)",
        "ne_yapar": "Uydu, roket, uzay gözlemi teknolojileri.",
        "calisma_alanlari": ["TUA (Türkiye Uzay Ajansı)", "Roketsan", "TUSAŞ", "CERN/ESA staj"],
        "onemli_dersler": "Astronomi, uzay mekaniği, yörünge, uydu haberleşme",
        "avantaj": "TR uzay programı genişliyor, yeni alan",
        "dezavantaj": "Dar iş alanı, henüz piyasa küçük",
        "maas_aralik": "Giriş 45-70K, uzman 90-160K",
    },
    "robotik": {
        "ad": "Robotik ve Mekatronik", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "310-440 (SAY)",
        "ne_yapar": "Otonom sistemler, endüstriyel robotlar, mekatronik tasarım.",
        "calisma_alanlari": ["Otomotiv (TOGG)", "Savunma (ASELSAN IHA/SIHA)", "Fabrika otomasyonu"],
        "onemli_dersler": "Kontrol sistemleri, mikroişlemci, mekanik, AI",
        "avantaj": "Gelecek mesleği, savunma projeleri, Ar-Ge",
        "dezavantaj": "Yeni alan, bazı üniversitelerde program yok",
        "maas_aralik": "Giriş 38-55K, uzman 70-140K",
    },

    # İş/yönetim
    "finans": {
        "ad": "Finans / Bankacılık", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "280-420 (EA)",
        "ne_yapar": "Finansal analiz, yatırım, bankacılık operasyonları.",
        "calisma_alanlari": ["Bankalar (uzman yardımcısı)", "BDDK/SPK", "Finans kuruluşları", "Kurumsal finans"],
        "onemli_dersler": "Muhasebe, finansal yönetim, yatırım teorisi, portföy",
        "avantaj": "Banka giriş sınavları geniş istihdam",
        "dezavantaj": "Bankacılık yoğun performans baskısı",
        "maas_aralik": "Giriş 35-55K, 5 yıl 70-140K, üst düzey 200K+",
    },
    "pazarlama": {
        "ad": "Pazarlama / Reklam", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "240-380 (EA)",
        "ne_yapar": "Marka yönetimi, dijital pazarlama, tüketici analizi.",
        "calisma_alanlari": ["Reklam ajansları", "FMCG (Unilever, Coca-Cola)", "Dijital ajanslar", "Startup"],
        "onemli_dersler": "Tüketici davranışı, dijital pazarlama, marka yönetimi",
        "avantaj": "Yaratıcı + analitik, dijital çağda talep yüksek",
        "dezavantaj": "Deadline yoğun, uzun mesai",
        "maas_aralik": "Giriş 25-42K, uzman 55-100K",
    },
    "muhasebe": {
        "ad": "Muhasebe / Mali Müşavirlik", "alan": "EA", "sure_yil": 4,
        "puan_aralik": "220-360 (EA)",
        "ne_yapar": "Şirket muhasebesi, vergi, denetim, mali müşavirlik.",
        "calisma_alanlari": ["Mali müşavir ofisleri", "Kurumsal muhasebe", "Vergi Dairesi (KPSS)", "Denetim (Big 4)"],
        "onemli_dersler": "Genel muhasebe, vergi, denetim, maliyet muhasebesi",
        "avantaj": "Kendi SMMM açma, her sektörde talep",
        "dezavantaj": "Staj + SMMM sınavı uzun (3+ yıl)",
        "maas_aralik": "Stajyer 25K, SMMM 50-200K (kendi ofis)",
    },

    # Sağlık dışı sağlık
    "radyoterapi": {
        "ad": "Odyoloji / Radyoterapi / Sağlık Teknikerliği", "alan": "SAY", "sure_yil": 2,
        "puan_aralik": "200-340 (SAY, MYO)",
        "ne_yapar": "Hastanelerde tıbbi cihaz, görüntüleme, laboratuvar destek.",
        "calisma_alanlari": ["Hastane", "Özel görüntüleme merkezi"],
        "onemli_dersler": "Radyoloji, hasta bakımı, cihaz kullanımı",
        "avantaj": "Kısa süre (2 yıl), hızlı iş",
        "dezavantaj": "Ön lisans, lisans tamamlama gerekli",
        "maas_aralik": "Giriş 25-35K, deneyimli 38-55K",
    },
    "dietisyen": {
        "ad": "Diyetisyen (Beslenme-Diyetetik ile aynı)", "alan": "SAY", "sure_yil": 4,
        "puan_aralik": "340-440 (SAY)",
        "ne_yapar": "Bkz. beslenme",
        "calisma_alanlari": ["Hastane", "Özel muayene", "Spor"],
        "onemli_dersler": "Biyokimya, diyet, klinik beslenme",
        "avantaj": "Sosyal medya görünürlük, kendi muayene",
        "dezavantaj": "Piyasa yoğun rekabet",
        "maas_aralik": "Giriş 25-40K, kendi muayene 50-150K+",
    },
}

# Eş anlamlı / alternatif yazımlar
_ALIASES = {
    "kimya muhendisi": "kimya muhendisligi",
    "kimya mühendisliği": "kimya muhendisligi",
    "kimya mühendisi": "kimya muhendisligi",
    "bilgisayar muhendisi": "bilgisayar muhendisligi",
    "bilgisayar mühendisliği": "bilgisayar muhendisligi",
    "yazilim muhendisi": "bilgisayar muhendisligi",
    "yazilim muhendisligi": "bilgisayar muhendisligi",
    "yazılım mühendisliği": "bilgisayar muhendisligi",
    "bilgisayar": "bilgisayar muhendisligi",
    "tıp": "tip",
    "doktor": "tip",
    "dis hekimi": "dis hekimligi",
    "diş hekimliği": "dis hekimligi",
    "diş hekimi": "dis hekimligi",
    "mimar": "mimarlik",
    "mimarlık": "mimarlik",
    "avukat": "hukuk",
    "psikolog": "psikoloji",
    "makine muhendisi": "makine muhendisligi",
    "makine mühendisliği": "makine muhendisligi",
    "elektrik elektronik muhendisi": "elektrik elektronik",
    "elektrik mühendisliği": "elektrik elektronik",
    "endustri muhendisi": "endustri muhendisligi",
    "endüstri mühendisliği": "endustri muhendisligi",
    "eczaci": "eczacilik",
    "eczacı": "eczacilik",
    "çevirmen": "mutercim tercuman",
    "cevirmen": "mutercim tercuman",

    # 23 Nisan — 50+ meslek genişleme aliases
    "veteriner hekim": "veteriner",
    "veteriner hekimliği": "veteriner",
    "fizyoterapist": "fizyoterapi",
    "fizyoterapi ve rehabilitasyon": "fizyoterapi",
    "hemşire": "hemsirelik",
    "hemsire": "hemsirelik",
    "diyetisyen": "beslenme",
    "beslenme ve diyetetik": "beslenme",
    "ebe": "ebelik",
    "inşaat mühendisi": "insaat muhendisligi",
    "insaat muhendisi": "insaat muhendisligi",
    "inşaat mühendisliği": "insaat muhendisligi",
    "harita muhendisi": "harita muhendisligi",
    "harita mühendisliği": "harita muhendisligi",
    "geomatik": "harita muhendisligi",
    "cevre muhendisi": "cevre muhendisligi",
    "çevre mühendisliği": "cevre muhendisligi",
    "gida muhendisi": "gida muhendisligi",
    "gıda mühendisliği": "gida muhendisligi",
    "bilisim": "bilisim sistemleri",
    "bilişim sistemleri": "bilisim sistemleri",
    "yapay zeka": "yapay zeka muhendisligi",
    "yapay zekâ": "yapay zeka muhendisligi",
    "ai muhendisi": "yapay zeka muhendisligi",
    "ai mühendisi": "yapay zeka muhendisligi",
    "makine ogrenmesi": "yapay zeka muhendisligi",
    "makine öğrenmesi": "yapay zeka muhendisligi",
    "siber güvenlik": "siber guvenlik",
    "cyber security": "siber guvenlik",
    "güvenlik mühendisi": "siber guvenlik",
    "biyomedikal muhendisi": "biyomedikal",
    "biyomedikal mühendisi": "biyomedikal",
    "havacılık": "havacilik muhendisligi",
    "havacilik": "havacilik muhendisligi",
    "uzay muhendisi": "uzay muhendisligi",
    "uzay mühendisi": "uzay muhendisligi",
    "uzay teknolojileri": "uzay muhendisligi",
    "gemi mühendisi": "gemi insaati",
    "gemi muhendisi": "gemi insaati",
    "gemi inşaatı": "gemi insaati",
    "metalurji mühendisi": "metalurji",
    "malzeme mühendisi": "metalurji",
    "maden mühendisi": "maden muhendisligi",
    "maden mühendisliği": "maden muhendisligi",
    "jeoloji mühendisi": "jeoloji",
    "jeoloji mühendisliği": "jeoloji",
    "ekonomi": "iktisat",
    "ekonomist": "iktisat",
    "iktisatçı": "iktisat",
    "uluslararası ilişkiler": "uluslararasi iliskiler",
    "diplomat": "uluslararasi iliskiler",
    "siyaset bilimi ve kamu yönetimi": "siyaset bilimi",
    "kamu yönetimi": "siyaset bilimi",
    "kaymakam": "siyaset bilimi",
    "gazeteci": "gazetecilik",
    "medya": "gazetecilik",
    "sınıf öğretmeni": "sinif ogretmenligi",
    "sinif ogretmeni": "sinif ogretmenligi",
    "matematik öğretmeni": "matematik ogretmenligi",
    "matematik ogretmeni": "matematik ogretmenligi",
    "pdr": "psikolojik danismanlik",
    "rehber öğretmen": "psikolojik danismanlik",
    "psikolojik danışman": "psikolojik danismanlik",
    "arkeolog": "arkeoloji",
    "filozof": "felsefe",
    "tarihçi": "tarih",
    "tarihci": "tarih",
    "edebiyat": "turk dili edebiyati",
    "türk dili ve edebiyatı": "turk dili edebiyati",
    "türkçe öğretmenliği": "turk dili edebiyati",
    "ingiliz dili": "ingiliz dili edebiyati",
    "ingilizce": "ingiliz dili edebiyati",
    "robotik mühendisliği": "robotik",
    "mekatronik": "robotik",
    "mekatronik mühendisliği": "robotik",
    "bankacı": "finans",
    "bankacılık": "finans",
    "finansal analist": "finans",
    "pazarlamacı": "pazarlama",
    "reklam": "pazarlama",
    "mali müşavir": "muhasebe",
    "smmm": "muhasebe",
    "muhasebeci": "muhasebe",
    "radyoloji teknikeri": "radyoterapi",
    "sağlık teknikeri": "radyoterapi",
}


def _normalize_query(q: str) -> str:
    """Türkçe karakter + lower."""
    tr_fold = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s",
                              "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
                              "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    return q.strip().lower().translate(tr_fold)


async def get_career_info(meslek: str) -> dict:
    """Meslek/bölüm tanıtımı — Claude'un kullanacağı tool.

    Args:
        meslek: "Kimya mühendisliği", "Tıp", "Hukuk" vb.

    Returns:
        dict — yapılandırılmış meslek bilgisi veya {"error": "..."}
    """
    if not meslek:
        return {"error": "meslek parametresi bos"}

    q_raw = meslek.strip()
    q_norm = _normalize_query(q_raw)

    # Direct match
    if q_norm in _CAREERS:
        data = _CAREERS[q_norm].copy()
        data["_source"] = "career_info"
        return data

    # Alias match
    if q_norm in _ALIASES:
        key = _ALIASES[q_norm]
        data = _CAREERS[key].copy()
        data["_source"] = "career_info"
        return data

    # Substring search (esnek)
    for key in _CAREERS:
        if key in q_norm or q_norm in key:
            data = _CAREERS[key].copy()
            data["_source"] = "career_info (substring)"
            return data

    # Miss — Claude kendi bilgisinden üretsin
    return {
        "error": f"'{q_raw}' icin hazir tanitim yok. Claude kendi bilgisiyle cevap versin.",
        "mevcut_meslekler": sorted([_CAREERS[k]["ad"] for k in _CAREERS]),
    }


def list_all_careers() -> list[str]:
    """Tüm mesleklerin isim listesi (debug/doc için)."""
    return sorted([_CAREERS[k]["ad"] for k in _CAREERS])


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    async def test():
        cases = [
            "Kimya mühendisliği",
            "kimya muhendisligi",
            "tıp",
            "doktor",
            "bilgisayar",
            "yazılım mühendisliği",
            "avukat",
            "olmayan meslek xyz",
        ]
        for m in cases:
            r = await get_career_info(m)
            if "error" in r:
                print(f"  ✗ '{m}' → {r['error'][:60]}")
            else:
                print(f"  ✓ '{m}' → {r['ad']} ({r['alan']}, {r['puan_aralik']})")

        print(f"\nToplam meslek: {len(list_all_careers())}")

    asyncio.run(test())
