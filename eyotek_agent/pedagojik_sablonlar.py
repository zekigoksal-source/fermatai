"""
FermatAI — Pedagojik Şablon Kütüphanesi (22.1n-neo FAZ 2.2)
=============================================================

35+ şablon — belirli bir tetikte bot kullanıyor.
Kategoriler:
  - SINAV_YAKIN (YKS/TYT/AYT geri sayım motivasyonu)
  - DENEME_SONRASI (net değişim — artış/düşüş tepkisi)
  - HEDEF_BELIRLEME (kısa-orta-uzun vade)
  - CALISMA_PLANI_FEEDBACK (plan kalite değerlendirmesi)
  - VELI_ILETISIM (veli modülü için, 1 Eylül sonrası)
  - KONU_GERI_BILDIRIM (anladım/eksik/tekrar)
  - OGRETMEN_YONLENDIRME
  - ZAMAN_YONETIMI_KRIZ
  - DERS_CAKISMA_COZUM
  - KRIZ_DESTEK (kaygı, motivasyon düşüşü)

KULLANIM:
  get_by_trigger("net_dustu_5+") → şablon döner, Claude degisken slotlari doldurur
  list_by_kategori("SINAV_YAKIN") → kategorideki tüm şablonlar
"""
from __future__ import annotations

import re
import random
from typing import Optional
from db_pool import db_fetch, db_fetchrow, db_execute


SABLONLAR = [
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 1: SINAV_YAKIN (YKS geri sayım)
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "yks_7_gun",
        "kategori": "SINAV_YAKIN", "alt_tip": "7gun",
        "trigger_desc": "YKS'ye tam 7 gün kala, öğrenciye özel son hafta rehberi",
        "sablon_metin": (
            "{isim}, 7 gün. 🎯\n\n"
            "Bundan sonra yeni konu YOK. Yapman gereken:\n"
            "- Her gün 1 TYT + 1 AYT denemesi (saat ayarı dahil)\n"
            "- Yanlışlarını 20 dakikada analiz et\n"
            "- Yeni test çözme — eski denemelere dön\n"
            "- Son 3 gün: sadece format + uyku ritmi\n\n"
            "*{sinif_akran_sayisi}* aynı sınıftakiyle yarışıyorsun, *{istatistik}*. "
            "Rakamlar senin tarafında — soğukkanlı kal.\n\n"
            "_Bugünkü planın ne?_"
        ),
        "degisken_slotlar": "isim,sinif_akran_sayisi,istatistik",
        "uygulama_notu": "sinav_tarihine_kala <= 7 gün ise",
    },
    {
        "slug": "yks_3_gun",
        "kategori": "SINAV_YAKIN", "alt_tip": "3gun",
        "trigger_desc": "Son 72 saat — sıcak motivasyon + pratik uyarı",
        "sablon_metin": (
            "{isim}, 3 gün. Artık yol haritası değişiyor.\n\n"
            "*SON 72 SAAT KURALI:*\n"
            "- Yeni konu öğrenme — öğrenemediğini kabullen\n"
            "- Deneme çözme — analiz daha önemli\n"
            "- Yarın erken uyu, saat ayarı = YKS saati\n"
            "- Kahve azalt (uyku bozar)\n"
            "- YKS günü sadece kimlik + kalem + su + atıştırmalık\n\n"
            "*Öğrendiklerin beyinden uçmaz — sadece yorulma sakın.* "
            "Bu 72 saat öğrenmek için değil, *hazırlığını korumak* için.\n\n"
            "_Nasıl hissediyorsun?_"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "sinav_tarihine_kala <= 3 gün",
    },
    {
        "slug": "yks_sabahi",
        "kategori": "SINAV_YAKIN", "alt_tip": "sinav_sabahi",
        "trigger_desc": "YKS sabah — öğrenci bot'a mesaj atarsa",
        "sablon_metin": (
            "{isim}, bugün senin günün. ✨\n\n"
            "1 yıl boyunca her çözdüğün sorular, her yanlış, her doğru — hepsi bugünün "
            "içinde. Sınav odasına giren sen yalnız değilsin — Cahit Arf, Aziz Sancar, "
            "seni öğretmiş hocan, ailen — hepsi elinde.\n\n"
            "*SON HATIRLATMA:*\n"
            "- Nefes derin, omurga dik\n"
            "- İlk 5 soru zor gelirse geç\n"
            "- Saat kontrolü 15'de bir\n"
            "- Son 10 dakika boş bırakmaları doldur (yanlış silinir)\n\n"
            "*Başarılar. Dönünce konuşuruz.* 🎓"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "sinav günü sabah (saat 06:00-10:00), öğrenci mesajı",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 2: DENEME_SONRASI
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "net_arti_10",
        "kategori": "DENEME_SONRASI", "alt_tip": "buyuk_artis",
        "trigger_desc": "Son denemede +10 net ARTIŞ — nasıl oldu sorulur",
        "sablon_metin": (
            "{isim}, *+{artis} net*. Bu değişim rastgele değil.\n\n"
            "Sana iki soru sorayım:\n"
            "1. Bu hafta farklı ne yaptın? (çalışma yöntemi, uyku, günlük ritüel)\n"
            "2. En çok hangi ders/konuda artış var?\n\n"
            "*Bunu biliyor olman sürdürülebilirliği sağlar.* "
            "'Şanstı' demek kolay ama doğru değil — patternin gerçek. "
            "Neyi yaptıysan, devam et.\n\n"
            "_Mucize yok, metod var._ 🎯"
        ),
        "degisken_slotlar": "isim,artis",
        "uygulama_notu": "tyt/ayt son deneme toplam_net - önceki >= 10",
    },
    {
        "slug": "net_dustu_5_10",
        "kategori": "DENEME_SONRASI", "alt_tip": "orta_dusus",
        "trigger_desc": "Son denemede 5-10 net düşüş — destekleyici + analiz yönlendirme",
        "sablon_metin": (
            "{isim}, *-{dusus} net*. Hayal kırıklığı doğal.\n\n"
            "Ama önce bir şey söylemek isterim: *tek deneme = tek fotoğraf, yıl = film.* "
            "{son_3_ortalama} net ortalaman var — bugün altında kaldın. Geçici.\n\n"
            "Bir şeyler değişti — anlayalım. Sana 3 soru:\n"
            "1. Fiziksel: dün kaç saat uyudun?\n"
            "2. Duygusal: hazırlıkta kaygı mı, motivasyon mu düştü?\n"
            "3. Teknik: hangi ders ani düştü?\n\n"
            "*Hatayı değil, sebebini bulalım. Bir sonraki deneme yine sen varsın.*"
        ),
        "degisken_slotlar": "isim,dusus,son_3_ortalama",
        "uygulama_notu": "-5 ile -10 arası düşüş",
    },
    {
        "slug": "net_dustu_10+",
        "kategori": "DENEME_SONRASI", "alt_tip": "buyuk_dusus",
        "trigger_desc": "10+ net düşüş — kriz destek + kök sebep araştırması",
        "sablon_metin": (
            "{isim}, biliyorum. *-{dusus} net* büyük.\n\n"
            "İlk önce: *sen iyi misin?* Denemeden önce bir şey olmadı mı? (kavga, "
            "uyku, hastalık, motivasyon kaybı, kişisel mesele)\n\n"
            "Deneme sayıdır, ama sen daha fazlasısın. Bazen hayat araya giriyor. "
            "Yargılamıyorum — *paylaş, birlikte çözelim.*\n\n"
            "Bir sonraki deneme {gun_sayisi} gün sonra. O zamana kadar odak: "
            "1) Uyku düzeni, 2) 1 konu tekrarı (hayranlık = daha hızlı dönüş), "
            "3) Kendine şefkat.\n\n"
            "_Yanındayım — bu geçici._"
        ),
        "degisken_slotlar": "isim,dusus,gun_sayisi",
        "uygulama_notu": "-10+ net düşüş, empati + psikolojik destek odaklı",
    },
    {
        "slug": "ilk_deneme",
        "kategori": "DENEME_SONRASI", "alt_tip": "ilk",
        "trigger_desc": "Öğrencinin ilk denemesi — benchmark oluşturma",
        "sablon_metin": (
            "{isim}, ilk denemen tamamlandı — *{toplam_net} net*. Bundan sonra bu "
            "*BASELINE* (referans). Her deneme buna karşı değil, kendine karşı.\n\n"
            "*Sana net bir plan çıkarayım:*\n"
            "- Güçlü ders: {guclu_ders} — koruyacağız\n"
            "- Fırsat ders: {firsat_ders} — bu yıl +{potansiyel} net kazanırsın\n"
            "- Sürekli çalışma: her gün 2-3 saat, 30dk analiz\n\n"
            "*YKS'ye {kala} gün var. Zaman yeterli, yön önemli.* "
            "Hedefini konuşalım mı?"
        ),
        "degisken_slotlar": "isim,toplam_net,guclu_ders,firsat_ders,potansiyel,kala",
        "uygulama_notu": "öğrencinin ilk deneme kaydı",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 3: HEDEF_BELIRLEME
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "hedef_uzun_vade",
        "kategori": "HEDEF_BELIRLEME", "alt_tip": "uzun",
        "trigger_desc": "Uzun vade hedef (YKS, bölüm) belirleme — 3 aşama",
        "sablon_metin": (
            "{isim}, hedef = bugünü şekillendiren yarının resmi.\n\n"
            "3 katmanda konuşalım:\n\n"
            "*1️⃣ Uzun vade (YKS → bölüm → kariyer):*\n"
            "- Hangi bölüm/üniversite istiyorsun?\n"
            "- Neden? (para, ilgi alanı, aile, prestij — hepsi geçerli, bilmek gerek)\n\n"
            "*2️⃣ Orta vade (bu dönem → Mayıs):*\n"
            "- {mevcut_net} → {hedef_net} net için neler lazım?\n\n"
            "*3️⃣ Kısa vade (bu hafta):*\n"
            "- 1 ders + 3 konu + 1 deneme — gerçekçi mi?\n\n"
            "_Hangisinden başlayalım?_ 🎯"
        ),
        "degisken_slotlar": "isim,mevcut_net,hedef_net",
        "uygulama_notu": "öğrenci hedef konusu açarsa",
    },
    {
        "slug": "hedef_kisa_vade_haftalik",
        "kategori": "HEDEF_BELIRLEME", "alt_tip": "haftalik",
        "trigger_desc": "Haftalık hedef belirleme — SMART criteria",
        "sablon_metin": (
            "*Bu Hafta İçin Net Hedef*\n\n"
            "Hedef SMART olmalı:\n"
            "- *S*pesifik: 'fizik çalışacağım' ❌ → 'fizik kaldırma kuvveti 20 soru' ✓\n"
            "- *M*easurable: 'iyi çalışacağım' ❌ → 'her gün 2 saat' ✓\n"
            "- *A*chievable: kapasiten dahilinde\n"
            "- *R*elevant: YKS'ye uygun\n"
            "- *T*ime-bound: Pazar akşama kadar\n\n"
            "*Senin bu haftaki spesifik hedefin ne?* (ders + konu + sayı + süre)"
        ),
        "degisken_slotlar": "",
        "uygulama_notu": "Pazartesi sabahı veya hedef belirsizse",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 4: CALISMA_PLANI_FEEDBACK
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "plan_cok_iyi",
        "kategori": "CALISMA_PLANI_FEEDBACK", "alt_tip": "iyi",
        "trigger_desc": "Öğrenci iyi dengeli plan yaptı — pekiştir",
        "sablon_metin": (
            "{isim}, planın sağlam. Şöyle okuyorum:\n\n"
            "✅ *Çeşitlilik* — tek dersi ezmiyorsun, beyin yorgunluğu azalır (CLT)\n"
            "✅ *Mola ayarı* — Pomodoro ritmine yakın, sürdürülebilir\n"
            "✅ *Zayıf ders odağı* — {zayif_ders} 2 saat, doğru ağırlık\n\n"
            "*Kritik soru:* Her gün aynı plan mı, esnek mi? Yorgun olduğun gün "
            "azaltma izni ver kendine. Disiplin = esnek devamlılık."
        ),
        "degisken_slotlar": "isim,zayif_ders",
        "uygulama_notu": "plan 5+ ders dengeli içeriyorsa",
    },
    {
        "slug": "plan_tek_ders",
        "kategori": "CALISMA_PLANI_FEEDBACK", "alt_tip": "dengesiz",
        "trigger_desc": "Öğrenci tek derse aşırı ağırlık verdi — Cognitive Load uyarısı",
        "sablon_metin": (
            "{isim}, planına bir şey fark ettim:\n\n"
            "{tek_ders} için günde {saat} saat — epey yoğun. Bu beyin için risk:\n"
            "- 3+ saat tek ders → *Cognitive Load Theory* sınırı aşılır\n"
            "- Aynı ders iki oturumda 90 dk + mola → 2x verim\n"
            "- Farklı ders paralel çalıştırmak (dönüşümlü) hatırlamayı güçlendirir\n\n"
            "Alternatif öneri: sabah {tek_ders} 90dk → öğle {baska_ders} → akşam {tek_ders} "
            "90dk.\n\n"
            "_Aynı toplam süre, daha iyi çıktı._"
        ),
        "degisken_slotlar": "isim,tek_ders,saat,baska_ders",
        "uygulama_notu": "tek derse 4+ saat atayan öğrenci",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 5: VELI_ILETISIM (veli modülü için, 1 Eylül sonrası)
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "veli_haftalik_digest",
        "kategori": "VELI_ILETISIM", "alt_tip": "digest", "hedef_rol": "veli",
        "trigger_desc": "Veli haftalık özet — pozitif + bilgilendirici",
        "sablon_metin": (
            "Sayın {veli_adi},\n\n"
            "{cocuk_ad}'nın bu haftaki akademik özeti:\n\n"
            "📊 *Sayısal Durum*\n"
            "- Deneme: {deneme_net} net (geçen hafta {onceki_net})\n"
            "- Devamsızlık: {devamsizlik_saat} saat\n"
            "- Etüt katılımı: {etut_sayisi}\n\n"
            "🌱 *Bu Hafta Fark Ettiğim*\n"
            "- {pozitif_nokta}\n"
            "- {gelistirilecek}\n\n"
            "💡 *Evde Yapabilecekleriniz*\n"
            "- {oneri}\n\n"
            "_Sorunuz varsa rahatça yazabilirsiniz._\n"
            "Fermat Eğitim Kurumları"
        ),
        "degisken_slotlar": "veli_adi,cocuk_ad,deneme_net,onceki_net,devamsizlik_saat,etut_sayisi,pozitif_nokta,gelistirilecek,oneri",
        "uygulama_notu": "Pazar akşamı, VELI_MODULE_ACTIVE=true",
    },
    {
        "slug": "veli_destek_cocugu_zorlaniyor",
        "kategori": "VELI_ILETISIM", "alt_tip": "destek", "hedef_rol": "veli",
        "trigger_desc": "Çocuk akademik zorluk — veli nasıl destek olur",
        "sablon_metin": (
            "Sayın {veli_adi},\n\n"
            "{cocuk_ad}'nın bu dönemde zorluk yaşadığını fark ettim. Aileye *3 pratik "
            "yaklaşım* önermek isterim (eğitim bilimleri literatüründen):\n\n"
            "🔹 *Büyüme Zihniyeti* (Carol Dweck): 'Bunu yapamazsın' değil, 'Bunu "
            "HENÜZ yapamıyorsun, beyin öğrenecek' — küçük nüans, büyük fark.\n\n"
            "🔹 *Performans vs Kişilik*: 'Tembel çocuk' etiketi yerine 'bugün "
            "motive olmayan eylem' — eylemi değerlendirin, kimliği değil.\n\n"
            "🔹 *Süreç odağı*: 'Kaç net aldın' yerine 'nasıl çalıştın, zevk aldın "
            "mı' sorun — sonuç değil süreç iç motivasyonu besler.\n\n"
            "_Dilerseniz bir öğretmen görüşmesi ayarlayabiliriz._"
        ),
        "degisken_slotlar": "veli_adi,cocuk_ad",
        "uygulama_notu": "çocuk sentiment negatif 3+ gün ve veli mesaj atarsa",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 6: KONU_GERI_BILDIRIM
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "konu_anladim",
        "kategori": "KONU_GERI_BILDIRIM", "alt_tip": "anlaşildi",
        "trigger_desc": "Öğrenci 'anladım' dediyse — pekiştirme sorusuyla doğrula",
        "sablon_metin": (
            "Güzel — ama Feynman'ın bir kuralı var: *bir konuyu gerçekten anlamış "
            "mısın?* 12 yaşındaki bir çocuğa anlatabiliyorsan, evet.\n\n"
            "Sana mini test: *{konu}'yu 2 cümlede ben hiç bilmiyormuşum gibi "
            "anlat.* Teknik terim kullanabilirsin ama basit tut.\n\n"
            "_Bu 'uygulama' aşaması (Bloom L3) — ezberden farklı._"
        ),
        "degisken_slotlar": "konu",
        "uygulama_notu": "öğrenci 'anladım', 'tamam', 'oldu' dediğinde",
    },
    {
        "slug": "konu_tekrar_gerek",
        "kategori": "KONU_GERI_BILDIRIM", "alt_tip": "eksik",
        "trigger_desc": "Test sonucu konuda eksik — tekrar planı",
        "sablon_metin": (
            "{konu}'dan {yanlis} yanlış — önemli bir sinyal.\n\n"
            "*Tekrar planı* (Ebbinghaus aralıklı tekrar):\n"
            "- Bugün: 15dk özet + 5 basit soru\n"
            "- 3 gün sonra: 10 soru (orta zorluk)\n"
            "- 1 hafta sonra: kısa test (sadece bu konu)\n"
            "- 1 ay sonra: genel denemede çık, yerleşmiş mi bak\n\n"
            "*Bu döngü = hafızaya kazıma. Tek seferlik çalışmayla gelen, tek seferlik gider.*"
        ),
        "degisken_slotlar": "konu,yanlis",
        "uygulama_notu": "topic_tracker'da bir konunun hatası %50+",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 7: OGRETMEN_YONLENDIRME
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "etut_oneri",
        "kategori": "OGRETMEN_YONLENDIRME", "alt_tip": "etut",
        "trigger_desc": "Öğrenci konuda zorlanıyor — etüt önerisi",
        "sablon_metin": (
            "{isim}, bu konuyu birlikte aşmalıyız — *{ogretmen} Hoca* bu konunun uzmanı.\n\n"
            "*Etüt talebi oluşturayım mı?*\n"
            "- Ders: {ders}\n"
            "- Konu: {konu}\n"
            "- Uygun gün/saat: {saat_oneri}\n\n"
            "_Onaylıyorsan eyotek'e yazayım, {ogretmen} Hoca'ya bilgi gider._"
        ),
        "degisken_slotlar": "isim,ogretmen,ders,konu,saat_oneri",
        "uygulama_notu": "öğrenci 3+ kez aynı konuda zorluk ifade ettiyse",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 8: ZAMAN_YONETIMI_KRIZ
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "zaman_yetmiyor",
        "kategori": "ZAMAN_YONETIMI_KRIZ", "alt_tip": "panik",
        "trigger_desc": "Öğrenci 'zaman yetmiyor' diye panik — reframe",
        "sablon_metin": (
            "{isim}, zamanın yetmediği hissi gerçek ama durum ondan farklı.\n\n"
            "YKS'ye *{kala} gün* var. Bu {kala_saat} saat uyanık zaman demek. Çıkaralım:\n"
            "- Okul + etüt: {okul_saat} saat\n"
            "- Uyku + yemek: {temel_saat} saat\n"
            "- Net çalışma: *{net_saat} saat*\n\n"
            "*{net_saat} saat* = {hedef_konu} konu çalışması. Matematik: {kala_mat} saat. "
            "Yeterli *ama boşa geçemez*. Priorite:\n"
            "1. Zayıf ders odak (80/20 kuralı)\n"
            "2. Yeni konu DEĞİL, pekiştirme\n"
            "3. Deneme analizi > yeni test\n\n"
            "_Beraber planlayalım mı?_"
        ),
        "degisken_slotlar": "isim,kala,kala_saat,okul_saat,temel_saat,net_saat,hedef_konu,kala_mat",
        "uygulama_notu": "'yetişmiyor', 'zaman yok', 'az kaldı panik'",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 9: KRIZ_DESTEK (kaygı, motivasyon)
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "sinav_kaygisi",
        "kategori": "KRIZ_DESTEK", "alt_tip": "kaygi",
        "trigger_desc": "Sınav kaygısı beyanı — CBT + nefes egzersizi",
        "sablon_metin": (
            "{isim}, kaygıyı duyuyorum. Normal — vücut 'önemli' diyor.\n\n"
            "*Kaygı başarısızlık sinyali değil, hazırlık sinyali.* Performans için %30 "
            "kaygı ideal (Yerkes-Dodson). Aşarsa zararlı. Sana 2 araç:\n\n"
            "*1. 4-7-8 Nefes (hemen, 2 dakika):*\n"
            "- 4 sn burnundan al\n"
            "- 7 sn nefes tut\n"
            "- 8 sn ağızdan ver\n"
            "- 4 tur\n\n"
            "*2. Yeniden Çerçeveleme:*\n"
            "- 'Mahvolacağım' ❌ → 'Zorlanacağım ama hazırlandım' ✓\n"
            "- 'Herkes bakacak' ❌ → 'Kendi işime odaklanıyorum' ✓\n\n"
            "_Şimdi nefes egzersizini dene, konuşalım._"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "'kaygım var', 'stresliyim', 'panik olacağım'",
    },
    {
        "slug": "motivasyon_dusuk",
        "kategori": "KRIZ_DESTEK", "alt_tip": "motivasyon",
        "trigger_desc": "Motivasyon düşüklüğü — values clarification",
        "sablon_metin": (
            "{isim}, motivasyonun düşmesi iki şeyden olur:\n"
            "1. Hedef uzak görünüyor (duman içinde yol)\n"
            "2. Hedefle bağın zayıfladı (neden istediğini unuttun)\n\n"
            "Sana soru: *YKS'yi neden istiyorsun?* Kendi cümlenle — 'ailem istiyor' "
            "DEĞİL. 'Ben istiyorum çünkü...' tamamla.\n\n"
            "Çoğu öğrenci cevap veremez bu soruya. Veremezsen de normal. Ama sonra "
            "konuşalım — iç motivasyon (SDT kuramı) dış baskıdan 3x güçlü.\n\n"
            "_Kendi sesini bulma vaktidir._"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "'motive değilim', 'istemiyorum', 'boş geliyor' ve sentiment negatif",
    },
    {
        "slug": "perfeksiyonizm",
        "kategori": "KRIZ_DESTEK", "alt_tip": "mukemmeliyetci",
        "trigger_desc": "Her şey mükemmel olmalı baskısı — 'yeterince iyi' yaklaşımı",
        "sablon_metin": (
            "{isim}, sana bir gerçek:\n\n"
            "*Mükemmeliyetçilik çalışmayı yavaşlatır, ertelemeyi hızlandırır.*\n\n"
            "Şu anki durumun: 'Ya yüzde 100 yaparım ya hiç yapmam.' Bu zihin tuzak. "
            "Alternatif:\n\n"
            "*'Yeterince iyi' ilkesi:*\n"
            "- Kusursuz deneme yok — %75 hedefle, %85 ile şaşır\n"
            "- 'İlk taslak berbat olsun' — sonra iyileşir (Anne Lamott)\n"
            "- Tamamlanmamış her plan, başlanmamış mükemmel plandan iyi\n\n"
            "_Şimdi en küçük adımı söyle — 10 dakikada ne yapabilirsin?_"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "'mükemmel olmalı', 'hazır değilim', 'başaramayacağım panik'",
    },
    {
        "slug": "kiyas_travmasi",
        "kategori": "KRIZ_DESTEK", "alt_tip": "akran",
        "trigger_desc": "Akran kıyası — öğrencinin kendi yolunu kabul etme",
        "sablon_metin": (
            "{isim}, {akran} ile karşılaştırıyorsun kendini. Doğal, herkes yapıyor.\n\n"
            "*Ama bir şey unutma:*\n"
            "- {akran}'ın hazırlık öyküsü farklı (başlangıç noktası, aile durumu, kapasite)\n"
            "- Sen {akran}'ın birinci haftasını görmedin — son halini görüyorsun\n"
            "- Yarış YKS değil, kendi en iyi versiyonunla\n\n"
            "*Gerçek rakip: 3 ay önceki sen.* {farkliden_buyuk} net fark var aranızda — "
            "kendinden.\n\n"
            "Instagram gibi — herkes vitrinini gösterir. Sen süreci yaşıyorsun."
        ),
        "degisken_slotlar": "isim,akran,farkliden_buyuk",
        "uygulama_notu": "öğrenci başka öğrenci ismi + rekabet ifadesi",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 10: OGRETMEN DESTEĞİ (kendi aralarında)
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "ogretmen_ogrenci_dusuyor",
        "kategori": "OGRETMEN_DESTEK", "alt_tip": "uyari", "hedef_rol": "ogretmen",
        "trigger_desc": "Öğretmene: öğrencisinde düşüş var, pedagojik öneri",
        "sablon_metin": (
            "{ogretmen_ad} Hocam, {ogrenci} için bir sinyal:\n\n"
            "Son {n} denemede {ders}'te ortalama {dusus} net düşüş. Tek olaya bağlama "
            "ihtimali düşük — pattern var.\n\n"
            "*Görüşme yapmak isterseniz birkaç yaklaşım:*\n"
            "- *Neden sorusu* yerine *ne fark etti* — 'son zamanlarda neye farklı odaklanıyorsun?'\n"
            "- Kendi analizini sorun — öğrenci kendi hatalarını kendi söylerse öğrenir\n"
            "- Küçük hedef: 'gelecek 3 haftada tek konu' — başarı deneyimi iç motive eder\n\n"
            "_Rehberlik notu tutmak isterseniz yazarım._"
        ),
        "degisken_slotlar": "ogretmen_ad,ogrenci,n,ders,dusus",
        "uygulama_notu": "alert sistemi A1 trigger sonrası öğretmene",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 11: EK MOTIVASYON
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "uzun_sure_yok",
        "kategori": "KRIZ_DESTEK", "alt_tip": "geridonus",
        "trigger_desc": "Öğrenci uzun süre ortada yok, tekrar geri döndü",
        "sablon_metin": (
            "{isim}! Hoş geldin geri. {gun} gün oldu son konuşmamızdan.\n\n"
            "Merak etmedim ki — herkesin zor dönemleri olur. Sadece şunu söylemek "
            "istiyorum: *dönmek önemli şey.* Uzaklaşıp geri gelen öğrenciler genelde "
            "ne istediklerini daha net bilirler.\n\n"
            "Sana üç soru:\n"
            "1. Son {gun} gün ne oldu? (paylaşmasan da okay)\n"
            "2. YKS hedefin hala yerinde mi?\n"
            "3. Bugün başlamak istiyorsan, en küçük ilk adım ne?\n\n"
            "_Burada çalışmaya hazırsan, buradayım._"
        ),
        "degisken_slotlar": "isim,gun",
        "uygulama_notu": "son_gorusmeden >= 7 gün",
    },
    {
        "slug": "ilk_hafta_motivasyon",
        "kategori": "KRIZ_DESTEK", "alt_tip": "baslangic",
        "trigger_desc": "Yeni dönem ilk hafta motivasyon",
        "sablon_metin": (
            "{isim}, yeni dönemin ilk haftası. İşte beni en çok heyecanlandıran "
            "şey: *bugün başlangıçtayız ama sonu kendi yazacaksın.*\n\n"
            "Bu dönem önerim:\n"
            "- *Küçük başla, büyük kal* (Kaizen — sürekli iyileşme): "
            "İlk hafta günde 2 saat, sonra 2.5, sonra 3\n"
            "- *Tek değişken ekle*: Aynı anda 5 şey değiştirme. "
            "Önce uyku ritmi → yerleşince beslenme → sonra plan\n"
            "- *Günlük küçük kazanım*: Her gün 1 şey öğren, yaz, göster\n\n"
            "_2026.27 senin yılın — bugün ilk çizgini çiziyorsun._"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "sezon ilk haftası",
    },
    {
        "slug": "gun_sonu_refleksiyon",
        "kategori": "KRIZ_DESTEK", "alt_tip": "retrospektif",
        "trigger_desc": "Akşam refleksiyon — günün değerlendirmesi",
        "sablon_metin": (
            "{isim}, gün bitiyor. 3 soru:\n\n"
            "1. *Hangi 1 şey iyi gitti?* (kendini tebrik et)\n"
            "2. *Hangi 1 şey daha iyi olabilirdi?* (eleştiri değil, gözlem)\n"
            "3. *Yarın 1 küçük adım?* (mükemmel değil, gerçekçi)\n\n"
            "_Metakognisyon — öğrenme üzerine düşünme — öğrenmenin kendisinden güçlü._ "
            "İyi uykular. 🌙"
        ),
        "degisken_slotlar": "isim",
        "uygulama_notu": "akşam 20:00-23:00, öğrenci 'bittim/yattim' ifadesi",
    },
    # ═════════════════════════════════════════════════════════════════
    # KATEGORI 12: TEKNIK/PRATIK
    # ═════════════════════════════════════════════════════════════════
    {
        "slug": "ders_cakisma_cozum",
        "kategori": "DERS_CAKISMA", "alt_tip": "coklu",
        "trigger_desc": "Öğrenci birden fazla derse yetişemiyor",
        "sablon_metin": (
            "{isim}, 2+ dersi aynı anda ilerletmek zor — beyin böyle çalışmıyor.\n\n"
            "*Çözüm: Günlük Rotation*\n"
            "- Pzt-Çrş-Cum: {ana_ders_1} + {ana_ders_2}\n"
            "- Sal-Prş-Cmt: {ana_ders_3} + {ana_ders_4}\n"
            "- Pzr: İstediğin ders + deneme\n\n"
            "Her gün 2 ders, derin çalışma. Farklı dersler farklı günlerde → interleaving "
            "etkisi (aralıklı tekrar gibi) hafızayı güçlendirir.\n\n"
            "_Senin için dersleri önceliklendirelim mi?_"
        ),
        "degisken_slotlar": "isim,ana_ders_1,ana_ders_2,ana_ders_3,ana_ders_4",
        "uygulama_notu": "öğrenci 3+ ders aynı günde çakışma şikayeti",
    },
    {
        "slug": "yanlis_analiz_rehberi",
        "kategori": "CALISMA_PLANI_FEEDBACK", "alt_tip": "analiz",
        "trigger_desc": "Deneme sonrası yanlış analiz rehberi",
        "sablon_metin": (
            "*Yanlış Analizi Protokolü*\n\n"
            "Her yanlış 3 kategoriden birinde:\n\n"
            "🔴 *Bilgi Eksik* — Konuyu hiç bilmiyordun\n"
            "   → Çözüm: Konuyu öğren (4-6 saat)\n\n"
            "🟡 *Dikkat* — Bildin ama yanlış şıkka işaretledin\n"
            "   → Çözüm: Deneme-bitir-kontrol alışkanlığı (5dk son)\n\n"
            "🟢 *Zaman* — Son 15dk'da yetişemedin\n"
            "   → Çözüm: Süreli antrenman (pomodoro deneme)\n\n"
            "*Her kategoriyi sayıyla not et. 10 yanlışın 7'si bilgi eksikliğiyse = "
            "konu çalışacaksın. 5'i dikkat ise = pratik düzeni.*\n\n"
            "_Hangi yanlışını analiz edelim?_"
        ),
        "degisken_slotlar": "",
        "uygulama_notu": "deneme sonrası 'yanlışlarıma baktım' veya 'analiz'",
    },
]


async def hydrate_db() -> int:
    n = 0
    for s in SABLONLAR:
        await db_execute(
            """INSERT INTO pedagojik_sablonlar
               (slug, kategori, alt_tip, trigger_desc, sablon_metin, degisken_slotlar,
                uygulama_notu, hedef_rol)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (slug) DO UPDATE SET
                 kategori=EXCLUDED.kategori, alt_tip=EXCLUDED.alt_tip,
                 trigger_desc=EXCLUDED.trigger_desc, sablon_metin=EXCLUDED.sablon_metin,
                 degisken_slotlar=EXCLUDED.degisken_slotlar,
                 uygulama_notu=EXCLUDED.uygulama_notu, hedef_rol=EXCLUDED.hedef_rol""",
            s["slug"], s["kategori"], s.get("alt_tip", ""), s["trigger_desc"],
            s["sablon_metin"], s.get("degisken_slotlar", ""),
            s.get("uygulama_notu", ""), s.get("hedef_rol", "ogrenci")
        )
        n += 1
    return n


async def get_by_slug(slug: str) -> Optional[dict]:
    r = await db_fetchrow("SELECT * FROM pedagojik_sablonlar WHERE slug=$1", slug)
    return dict(r) if r else None


async def list_by_kategori(kategori: str, rol: str = "ogrenci") -> list[dict]:
    # Oturum Mentenans (21 Nisan 14:35) — BUG FIX: sablon_metin ve uygulama_notu
    # alanlari SELECT edilmiyordu, bu yuzden tool metin alamiyordu.
    # Ayrica hedef_rol NULL olabilir (eski hydrate), NULL'i da kabul et.
    rows = await db_fetch(
        """
        SELECT slug, alt_tip, trigger_desc, sablon_metin, uygulama_notu, hedef_rol
        FROM pedagojik_sablonlar
        WHERE kategori = $1
          AND (hedef_rol = $2 OR hedef_rol IS NULL)
        ORDER BY id
        """,
        kategori, rol
    )
    return [dict(r) for r in rows]


async def get_prompt_hint() -> str:
    """Claude system_prompt'a kisa referans."""
    return (
        "\n📋 PEDAGOJIK SABLON KUTUPHANESI (gerektiginde kategori bazli sablon uygula):\n"
        "  KATEGORILER:\n"
        "  - SINAV_YAKIN (7gun/3gun/sinav_sabahi)\n"
        "  - DENEME_SONRASI (net_arti_10 / net_dustu_5_10 / net_dustu_10+ / ilk_deneme)\n"
        "  - HEDEF_BELIRLEME (uzun_vade / kisa_vade_haftalik)\n"
        "  - CALISMA_PLANI_FEEDBACK (plan_cok_iyi / plan_tek_ders / yanlis_analiz_rehberi)\n"
        "  - KONU_GERI_BILDIRIM (konu_anladim / konu_tekrar_gerek)\n"
        "  - OGRETMEN_YONLENDIRME (etut_oneri)\n"
        "  - ZAMAN_YONETIMI_KRIZ (zaman_yetmiyor)\n"
        "  - DERS_CAKISMA (ders_cakisma_cozum)\n"
        "  - KRIZ_DESTEK (sinav_kaygisi / motivasyon_dusuk / perfeksiyonizm / kiyas_travmasi / "
        "uzun_sure_yok / ilk_hafta_motivasyon / gun_sonu_refleksiyon)\n"
        "  - VELI_ILETISIM (veli_haftalik_digest / veli_destek_cocugu_zorlaniyor)\n"
        "  - OGRETMEN_DESTEK (ogretmen_ogrenci_dusuyor)\n"
        "  Kullanim: Dogrudan kopyala-yapistir DEGIL — sablondan ilham al, kisiye ozelle.\n"
    )


if __name__ == "__main__":
    import asyncio, sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    async def main():
        n = await hydrate_db()
        print(f'{n} sablon eklendi')
        kat = await list_by_kategori("KRIZ_DESTEK")
        print(f'\nKRIZ_DESTEK: {len(kat)} sablon')
        for k in kat:
            print(f'  {k["slug"]} — {k["trigger_desc"][:70]}')
    asyncio.run(main())
