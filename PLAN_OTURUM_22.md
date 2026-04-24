# 🗺️ FermatAI — Oturum 22+ Eylem Planı

> **Hazırlandı:** 18 Nisan 2026 — Neo akşam seçim yapacak
> **Format:** Numaralı madde · "#3 yapalım" gibi referans alabilirsin
> **Kategori:** A (Web Arayüzü) · B (WhatsApp Kanalı) · C (Genel Proje/Ekosistem)
>
> Her madde: **Ne · Neden · Süre · Etki · Kanal · Ön koşul · Risk**

---

## 🖥️ A. WEB ARAYÜZÜ — 12 Eylem

### A1. Öğrenci Onboarding Turu (ilk giriş)
- **Ne:** İlk kez giren öğrenciye 3 balon şeklinde mini tur ("Foto at, Geçmiş, Mikrofon")
- **Neden:** Ecrin "sıkıcı chatgpt" dedi — ilk kullanımda yetenekleri göremeyince kayıp
- **Süre:** 2 saat
- **Etki:** 🟢 Orta (öğrenci retention)
- **Ön koşul:** Yok

### A2. Dosya Yükleme (PDF/Excel)
- **Ne:** Paperclip artık foto + PDF/Excel kabul etsin — deneme kağıdı, ödev, not PDF'i
- **Neden:** Öğrenci deneme PDF'ini atıp "analiz et" diyebilsin
- **Süre:** 3 saat
- **Etki:** 🔴 Yüksek (workflow hızlanır)
- **Ön koşul:** Yok
- **Risk:** PDF parse kalitesi

### A3. Canlı Deneme Optik Form Tarama
- **Ne:** Öğrenci cevap kağıdı fotosu atar → Vision → 120 soru analizi
- **Neden:** "Bu denemede doğru/yanlış/boş" hızlı analiz
- **Süre:** 6-8 saat (OMR pipeline karmaşık)
- **Etki:** 🔴 Yüksek (pedagojik bomba)
- **Ön koşul:** Vision prompt tuning

### A4. Öğrenci Dashboard (/ogrenci)
- **Ne:** Giriş yapınca statik chat yerine dashboard (net grafiği, zayıf konu haritası, çalışma planı)
- **Neden:** Neo "minimalizm" dedi ama öğrenciye proaktif görsel verebiliriz
- **Süre:** 8 saat
- **Etki:** 🟡 Orta
- **Risk:** Neo "akıcı konuşma" istedi, dashboard dağıtabilir

### A5. Matematik Editörü (MathLive)
- **Ne:** Öğrenci denklem yazabilsin — $x^2+5x-6=0$ gibi formülle soru sorsun
- **Neden:** Mobil klavye yerine görsel denklem yazma
- **Süre:** 4 saat
- **Etki:** 🟡 Orta
- **Ön koşul:** Yok

### A6. Proaktif Chart Önerileri
- **Ne:** Öğrenci metin halinde cevap alırken "📊 grafikle de göstereyim mi?" butonu
- **Neden:** Grafikler harika ama öğrenci isteyince bile fark etmiyor
- **Süre:** 2 saat
- **Etki:** 🟢 Orta

### A7. Ses Cevap (TTS)
- **Ne:** Bot cevapları sesli de dinlenebilsin (ElevenLabs veya browser TTS)
- **Neden:** Gözü yorgun öğrenci kulaklıkla dinler
- **Süre:** 3 saat
- **Etki:** 🟡 Orta (Türkçe TTS kalite sorunu)
- **Risk:** Ücretli TTS maliyet (~$20/ay)

### A8. Karanlık Mod (Dark Theme)
- **Ne:** Gece göz yormayan koyu tema
- **Neden:** Öğrenciler gece çalışır (08-20 kural dışında)
- **Süre:** 1 saat
- **Etki:** 🟢 Düşük

### A9. Paylaşılabilir Rapor (Export PDF)
- **Ne:** Öğrenci analizini PDF olarak indirsin, veliyle paylaşsın
- **Neden:** Veli iletişim köprüsü — direkt WhatsApp/email'e gönder
- **Süre:** 4 saat
- **Etki:** 🟡 Orta
- **Ön koşul:** PDF rapor modülü var (pasif), aktive

### A10. Bookmarklet / PWA
- **Ne:** Telefona sabitlenebilir uygulama (Chrome "Add to home screen" + manifest.json)
- **Neden:** Öğrenci her seferinde Wix'e girmesin, doğrudan iconla açsın
- **Süre:** 2 saat
- **Etki:** 🟢 Orta (UX)

### A11. Veli Portali (ayrı login)
- **Ne:** `veli_module.py` aktive edip web'de /veli paneli — veli çocuğunun özet, devamsızlık, mesaj
- **Neden:** Neo en sona bırakmıştı — şimdi web arayüzü hazır, basit
- **Süre:** 6 saat
- **Etki:** 🔴 Yüksek (yeni paydaş)
- **Risk:** Hassas veri, ACL dikkat

### A12. Multi-Device Açık Tutma (opsiyonel)
- **Ne:** Tek oturum modelinin tersi — admin/mudur aynı anda 2 cihaz (role-based)
- **Neden:** Neo "PC+iPad aynı anda" derse diye
- **Süre:** 2 saat
- **Etki:** 🟢 Düşük

---

## 📱 B. WHATSAPP KANALI — 8 Eylem

### B1. Foto Soru Pipeline Debug (İrem bug'ı)
- **Ne:** İrem (9720) 4 kez foto attı, sistem "göremedim" dedi — Vision API çağrısı neden fail
- **Neden:** Canlı öğrenci kaybı (sinirlenip çıktı) — production problem
- **Süre:** 2-3 saat (logs incelemeli)
- **Etki:** 🔴 Yüksek (öğrenci retention)
- **Ön koşul:** WA media download logu

### B2. İsim Çakışması Fix (Sistem tarafı)
- **Ne:** `search_students` 2+ sonuç → Claude "hangisi?" soruyor (prompt tamam)
- **Ama:** WP'da öğrenci "İrem" deyince hala yanlış profil gelmiş olabilir — gerçek test
- **Süre:** 1 saat test + fix
- **Etki:** 🔴 Yüksek

### B3. Öğretmen Telefon İmport
- **Ne:** 17 öğretmenin telefonu DB'de yok → `staff.phone` kolon + Mahsum'dan liste
- **Neden:** Öğretmenler "web kodu" alamıyor (sadece Vedat kayıtlı)
- **Süre:** 1 saat (liste gelince)
- **Etki:** 🟡 Orta
- **Ön koşul:** Mahsum'dan telefon listesi

### B4. İletişim Telafi Mekanizması
- **Ne:** Öğrenci frustration sinyali verince → 15-30 dk sonra telafi mesajı ("az önce [konu] için daha iyi cevap vereyim")
- **Neden:** Ecrin kayboldu, İrem kaybı — telafi fırsatı
- **Süre:** 4 saat
- **Etki:** 🟡 Orta
- **Ön koşul:** Alarm sistemi altyapısı (hazır ama pasif)
- **Risk:** Yanlış tetikleme, gece mesaj

### B5. WhatsApp Web Kodu Linklenebilir Hale
- **Ne:** Kod mesajında direkt tıklanabilir URL (telefon numarası otomatik populate)
- **Neden:** Öğrenci telefonu elle yazmak yerine "tıkla, pre-fill" ile hızlı giriş
- **Süre:** 2 saat
- **Etki:** 🟢 Orta
- **Risk:** Deep link kurulum

### B6. WP Filler Çeşitlilik Artırma
- **Ne:** Şu an 7 filler varyasyon var, uzun konuşmada tekrar ediyor → 20+'a çıkar
- **Neden:** Kullanıcı "bakıyorum" mesajını robot hissediyor
- **Süre:** 1 saat
- **Etki:** 🟢 Düşük

### B7. Admin Sesli Komut (Whisper)
- **Ne:** Neo WP'dan sesli mesaj → Whisper ASR → otomatik komut
- **Neden:** Mobil verimlilik — yazmak yerine konuş
- **Süre:** 3 saat
- **Etki:** 🟡 Orta (sadece admin için)
- **Ön koşul:** OpenAI Whisper API key

### B8. WP Bildirim Özetleri (Günlük Push)
- **Ne:** Her sabah 08:15 öğrenciye "bugün 2 zayıf konun var, fizik etüdün 14:00'te" mesajı
- **Neden:** Proaktif bildirim, öğrenci WP'yi açtığında zaten hazırlanmış
- **Süre:** 4 saat
- **Etki:** 🟡 Orta
- **Risk:** Spam algısı, opt-in şart

---

## 🏗️ C. GENEL PROJE / EKOSİSTEM — 16 Eylem

### 🔴 Kurum Otomasyonu

### C1. Alarm Sistemi Aktivasyonu
- **Ne:** `ALERTS_ACTIVE=True` — net düşüş, devamsızlık 100+, duygu kriz sinyali rehbere WP raporu
- **Neden:** Hazır ama kapalı, test edildi değil
- **Süre:** 1 gün (aktif + gözlem)
- **Etki:** 🔴 Yüksek (proaktif rehberlik)
- **Risk:** Yanlış tetiklenme, rehbere spam

### C2. Akıllı Etüt Planlama (Jarvis)
- **Ne:** Öğrenci "fizik etüdü" → topic_tracker + timetable → öğretmene rapor → onay → Eyotek'e yazma
- **Neden:** Neo'nun Jarvis vizyonu — otonom döngü
- **Süre:** 4 gün
- **Etki:** 🔴 Çok Yüksek (operasyonel devrim)
- **Ön koşul:** B3 (öğretmen telefonları), write_etut bug fix

### C3. Puan Tahmin + Yokatlas DB Genişletme
- **Ne:** Göktürk 398 puanıyla "nereye girersin" — DB şu an 465+ başlıyor → 10.000+ bölüme çıkar
- **Neden:** Öğrencilerin %60'ı DB kapsamı dışında
- **Süre:** 3 gün (Yokatlas scraper)
- **Etki:** 🔴 Yüksek
- **Risk:** Yokatlas scraping policy

### C4. Günlük Rapor Zenginleştirme
- **Ne:** 20:03 scheduler zaten çalışıyor ama içerik zayıf → kurum fotoğrafı + öneri + uyarı
- **Neden:** Her akşam 5dk'da Mahsum+Duygu kurum görünürlüğü
- **Süre:** 1 gün
- **Etki:** 🟡 Orta

### C5. Öğretmen Web Dashboard
- **Ne:** Kardelen Hoca web'den giriş → sınıfının grafikleri, etüt talepleri, kıyaslama
- **Neden:** Öğretmen kendi verisine bağımsız erişim
- **Süre:** 5 gün
- **Etki:** 🔴 Yüksek
- **Ön koşul:** B3 (öğretmen telefon)

### C6. Canlı Sınıf Ekranı (kurumda TV)
- **Ne:** Kurumdaki televizyonda canlı gösterim — bugün gelenler, anlık yoklama, duyurular
- **Neden:** Görünürlük + motivasyon + velilere "biz varız" mesajı
- **Süre:** 3 gün
- **Etki:** 🟡 Orta

### 🔵 Veri Kalitesi

### C7. Self-Validating RAG
- **Ne:** Claude çelişki görünce `atlas_suggestions` INSERT (şimdi yetki var) → haftada 1 admin kontrol
- **Neden:** Proaktif veri tespiti, reaktif değil
- **Süre:** 1 gün (cron + admin panel)
- **Etki:** 🟡 Orta (uzun vadede büyük)

### C8. OGM Vision Re-Import (konu-sayfa doğrulama)
- **Ne:** 390 kayıt için sayfa→konu eşleşmesini Vision ile tekrar doğrulama
- **Neden:** Bu gece 109 düzelttik ama hala kayan varsa yakalama
- **Süre:** 2 gün ($5-10 Vision maliyeti)
- **Etki:** 🟡 Orta

### C9. Sınıf İsim Normalizasyonu
- **Ne:** `[10] 10 SAY A`, `7-A`, `11 SAY VIB` → standart format (11 SAY, 10 SAY A)
- **Neden:** Analizlerde gürültü, Claude'a ek yük
- **Süre:** 2 saat
- **Etki:** 🟢 Orta

### C10. Duplicate ACL Temizlik
- **Ne:** `acl_users` 117 öğrenci + `students` 125 öğrenci — senkron değil
- **Neden:** Bir öğrenci ACL'de olmadan DB'de olabilir
- **Süre:** 1 saat
- **Etki:** 🟢 Düşük

### 🟢 Ticari Büyüme

### C11. Blog Otomatik Pipeline
- **Ne:** RAG'dan haftalık 2 YKS konu anlatımı → Wix blog otomatik push
- **Neden:** SEO + ücretsiz trafik + Fermat marka
- **Süre:** 3 gün
- **Etki:** 🟡 Orta (uzun vadede)
- **Ön koşul:** Wix Velo API

### C12. "Sor Bize" Public Widget
- **Ne:** Siteye giren herkese (guest) floating chat — "puan hesapla, bölüm öner"
- **Neden:** Ziyaretçi → potansiyel öğrenci dönüşümü
- **Süre:** 2 gün
- **Etki:** 🔴 Yüksek (müşteri akışı)
- **Risk:** API maliyeti (guest spam)

### C13. Dinamik Başarı Galerisi
- **Ne:** DB'de yerleşen öğrenciler → Wix sayfaya otomatik liste + foto + söz
- **Neden:** Sosyal kanıt, veli güveni
- **Süre:** 2 gün
- **Etki:** 🟡 Orta

### C14. Instagram/TikTok İçerik Üretim
- **Ne:** Günlük "soru+cevap" + Canva görsel → otomatik post
- **Neden:** Organik erişim, Fermat sosyal medya
- **Süre:** 4 gün
- **Etki:** 🟡 Orta

### 🟣 Mimari / Teknik Borç

### C15. Sistem Prompt Küçültme
- **Ne:** Prompt 18.000 token — bu gece temizledik ama hala büyük. Moduler yapı (rol bazlı prompt)
- **Neden:** Token maliyeti + latency
- **Süre:** 1-2 gün
- **Etki:** 🟡 Orta (hız kazanımı)
- **Risk:** Davranış regresyonu

### C16. Claude Streaming TTFT Optimizasyon
- **Ne:** p50 = 12s, p95 = 41s — tool sonrası Claude işleme gecikmesi
- **Neden:** Hız = deneyim (Neo'nun dediği)
- **Süre:** 2 gün (araştırma + prompt + tool call paralelleştirme v2)
- **Etki:** 🔴 Yüksek

---

## 🎯 NEO'YA ÖNERİM — TOP 5

Eğer sadece 5 seçsen, ben bunları koyarım (etki × aciliyet):

1. **C1 — Alarm sistemi aktivasyonu** (1 gün) — hazır, test edip canlıya al
2. **C2 — Akıllı etüt planlama** (4 gün) — Jarvis vizyonunun özü
3. **B1 — Foto soru pipeline fix** (3 saat) — üretim bug, öğrenci kaybı
4. **C3 — Puan tahmin + Yokatlas** (3 gün) — öğrenciler artık web'de sorabilir
5. **A11 — Veli portali** (6 saat) — yeni paydaş, web arayüzü hazır

**Toplam: ~1.5 hafta** — bu 5 ile kurum otomasyonu + pedagojik derinlik + ticari genişleme hepsi ilerler.

---

## 📋 NEO — AKŞAM GELDİĞİNDE

Şunları söyleyebilirsin:
- *"A3, A11, C1'den başlayalım"* — ben sırayla yaparım
- *"Top 5'inle devam et"* — sen başla
- *"Sadece kurum otomasyonu — C1-C6"* — odaklanmış ilerleriz
- *"Önce hızlı olanlar — 3 saatten az"* — A6, A8, B6, C10, C9 hızlı kazanımlar
- *"Öğrenci odaklı haftamız — A1, A2, A4, A7"* — web deneyimi

Hangisini seçersen, o maddenin detaylı planını açar başlarım.
