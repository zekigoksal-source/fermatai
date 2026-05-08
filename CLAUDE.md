# FermatAI — Claude Code Proje Hafızası

> Bu dosya Claude Code tarafından otomatik okunur. Her oturumda geçerlidir.

---

## Proje Özeti

**FermatAI** — Fermat Dershanesi için WhatsApp tabanlı yapay zeka LMS asistanı.
- LMS: `fermat.eyotek.com/v1` (ASP.NET WebForms)
- DB: PostgreSQL `postgresql://fermat:Ze-zzg10@localhost:5432/fermatai`
- AI: Hibrit — Ollama (yerel, 0 maliyet) + Claude Sonnet (bulut, tool-calling)
- Otomasyon: Playwright CDP (port 9222) → Eyotek yazma işlemleri
- Çalışma dizini: `C:\Users\zekig\OneDrive\Desktop\FermatAI`
- Python ortamı: `eyotek_agent\.venv` (Python 3.11)

## Mimari

```
WhatsApp mesaj/ses
    │
    ▼
whatsapp_bridge.py      ← FastAPI webhook (Meta API), ses→Whisper ASR
    │
    ▼
intent_parser.py        ← Kural + LLM (Haiku) niyet analizi
    │
    ▼
fermat_core_agent.py    ← Claude tool-calling + pedagojik muhakeme + ACL
    │           │
    │           └── PostgreSQL (asyncpg) — analitik sorgu
    ▼
eyotek_wrapper.py       ← Playwright CDP → Eyotek LMS okuma/yazma
    │
    ▼
WhatsApp yanıt → öğrenci/veli/öğretmen bildirimi
```

## Önemli Portlar
- PostgreSQL: 5432 (Docker)
- WhatsApp Bridge: **8001** (ChromaDB 8000 kullanıyor)
- Chrome CDP: 9222
- Ollama: 11434
- n8n: 5678

## Dosya Envanteri (eyotek_agent/)

| Dosya | Rol |
|-------|-----|
| `fermat_core_agent.py` | Ana beyin: Hibrit LLM (Ollama+Claude), ACL gate, pedagojik karar |
| `llm_router.py` | LLM soyutlama: yerel (Ollama) / bulut (Claude) hibrit yönlendirme |
| `eyotek_wrapper.py` | LMS otomasyon: write_etut, write_counsellor_note, read_* |
| `eyotek_agent.py` | Toplu scraping → PostgreSQL UPSERT |
| `whatsapp_bridge.py` | Meta webhook FastAPI, oturum yönetimi |
| `intent_parser.py` | WhatsApp komutu → IntentResult + tarih/saat parsing |
| `db_schema.sql` | Ana tablolar (students, attendance, staff, exams…) |
| `acl_schema.sql` | ACL rol matrisi + eyotek_action_log |
| `.env` | Tüm kimlik bilgileri (asla commit etme) |

## Kritik Teknik Bilgiler

### PostgreSQL Tabloları
- `students` — PK: `soz_no` (int), alanlar: `ad`, `soyad`, `sube`, `eyotek_id`, `sinif`, `program`
- `staff` — PK: `eyotek_id` (int), alanlar: `ad`, `soyad`, `gorev`, `eyotek_kullanici`
- `acl_users` — PK: `phone`, alanlar: `full_name`, `role`, `is_active`
- `attendance` — FK: `soz_no`, günlük yoklama snapshot

### Eyotek Pagination (ASP.NET WebForms)
- PostBack: `__doPostBack('GridView1','Page$N')`
- Pager linkler: `a[href*="Page$"]`
- `effective_total = total_pages` (max(total_pages, 9999) YAPMA — sonsuz döngü)
- Break condition: `first_sozno_after == first_sozno_before` → son sayfa aşıldı

### Türkçe Karakter Arama (PostgreSQL)
```python
_TR_TO_UPPER = str.maketrans("iığşüöç", "İIĞŞÜÖÇ")
name_upper = name.translate(_TR_TO_UPPER).upper()
# ILIKE ile kullan: WHERE UPPER(ad) ILIKE %name_upper%
```

### write_etut Akışı (15 adım)
1. Takvim sayfasına git → `DdlTeachers` ile öğretmen seç
2. Hedef tarih+ders_no hücresine tıkla (`GrdIndividualLessons_bi{N}_1_{row}`)
3. Modal açılır → `DdlAddClassesNormal` ile sınıf seç (opsiyonel — boşsa atla)
4. `TxtAddStudentNameNormal` → `BtnSearchStudent` → `LstAddStudentsNormal`'dan seç
5. Form doldur: etüt türü, devre, ders, konu, derslik
6. `BtnAddIndividualLessonSaveNormal` → kaydet

### Ders No → Saat Tablosu
```
1→09:00  2→09:45  3→10:30  4→11:15  5→12:00  6→12:45
7→14:00  8→14:45  9→15:30 10→16:15 11→17:00 12→17:45
13→18:30 14→19:15 15→20:00
```

### ACL Roller
```
admin/mudur → tüm araçlar, tüm okul
ogretmen   → write_etut OK, kendi sınıfları
veli       → sadece okuma, kendi çocuğu
guest      → engellendi
```

## Tamamlanan İşler (Nisan 2026, Oturum 1+2)

- [x] `write_etut()` v2.0 — takvim grid tıklama + modal (21 form ID haritalandı)
- [x] Pagination sonsuz döngü düzeltildi (eyotek_agent.py)
- [x] Staff modülü fix: URL `staff`, `needs_ara=True`, `eyotek_id` PK
- [x] `fermat_core_agent.py`: datetime import, dinamik tarih context, soz_no search
- [x] `eyotek_wrapper.py`: `class_name=""` crash fix
- [x] 125 öğrenci scrape + PostgreSQL import (soz_no 137–314)
- [x] 18 personel scrape (staff_export.json) — import bekliyor
- [x] `CALISTIR.bat` oluşturuldu (cleanup + import_staff + test_all)
- [x] `fermatai-daily-sync` zamanlanmış görev (her hafta içi 08:01)

## Tamamlanan Görevler (07 Nisan 2026 — Oturum 3)

- [x] `CALISTIR.bat` çalıştırıldı — 2 çöp kayıt silindi, 18 personel import edildi, 18/18 test geçti
- [x] Staff tablosu schema düzeltildi (eski `ik_no` PK → yeni `eyotek_id` PK)
- [x] `cleanup_db.py` emoji encoding fix (Windows cp1254 uyumu)
- [x] Konuşma geçmişi DB kaydı — `agent_conversations` tablosuna INSERT (`fermat_core_agent.py`)
- [x] `/agent` endpoint API key güvenlik — `AGENT_API_KEY` env ile Bearer token kontrolü
- [x] Rate limiting — per-phone max 10 mesaj/dakika (`whatsapp_bridge.py`)
- [x] `load_dotenv(override=True)` düzeltmesi — .env değerleri doğru yükleniyor
- [x] WhatsApp bridge CLI testi başarılı — agent cevap veriyor, konuşma DB'ye yazılıyor
- [x] `.claude/launch.json` oluşturuldu — whatsapp-bridge dev server
- [x] write_etut canlı dry-run testi başarılı — öğrenci bulma, öğretmen listeleme, parametre çıkarma OK
- [x] write_counsellor_note dry_run parametresi eklendi (güvenlik)
- [x] CDP fix: yeni sayfa açma (`new_page()`) + browser.close() kaldırıldı → tab çakışması çözüldü
- [x] Session auto-refresh: login sayfasına düşünce Chrome'dan taze cookie alıp devam eder
- [x] Hata screenshot: execute_eyotek_action hatasında logs/ klasörüne PNG kaydeder
- [x] `etut_records` ve `homework` DB tabloları oluşturuldu (db_schema.sql güncellendi)
- [x] `daily_briefing.py` oluşturuldu — sabah özetini oluştur (devamsız, riskli, agent kullanımı)
- [x] db_schema.sql güncellendi — staff tablosu eyotek_id PK (eski ik_no PK kaldırıldı)
- [x] Kişiselleştirilmiş karşılama — admin "Zeki Bey", öğrenci ismiyle hitap
- [x] `_get_caller_profile()` — telefon → profil çözümleme (ACL + students tablosu)
- [x] Öğrenci otomatik ACL kaydı — students.phone eşleşmesiyle ogrenci rolü atanır
- [x] Öğrenci yetki sınırlaması — sadece kendi verilerine erişim (prompt kuralı)
- [x] Öğrenci etkileşim loglama — konu bazlı pedagojik veri toplama (agent_conversations)
- [x] Agent prompt güncelleme — öğrenci etkileşim kuralları, motive edici hitap
- [x] 117 öğrenci telefon numarası DB'ye yüklendi (ogrCep+veliCep+anneCep+babaCep)
- [x] Eyotek 32 alt sayfa URL haritası keşfedildi (`student_page_map.json`)
- [x] 7 yeni read fonksiyonu: get_student_exams, behaviour, timetable, grades, specific_details, attendance (per-student)
- [x] 6 yeni DB tablosu: student_exams, student_behaviour, student_timetable, student_grades, student_details_specific, student_interactions
- [x] `get_student_analytics` genişletildi: davranış, bireysel sınav, etkileşim istatistikleri
- [x] STUDENT_SECTION_PATHS güncellendi: 8 yeni sayfa eklendi (toplam 29 path)
- [x] `eyotek_full_site_map.json` — Eyotek 180+ sayfa tam URL haritası (Öğrenci/Personel/Muhasebe/Raporlar)
- [x] `get_daily_etut(target_date)` — tarih filtreli günlük etüt listesi
- [x] `get_student_count_report()` — istatistik raporu
- [x] Etüt alt menü keşfi: Etüt Ara, Girişi, Girişi 2, Yoklama, Öğrenci Kontrol, Raporları, SMS Bildirim
- [x] Muhasebe rapor menüsü haritalandı: Kasa, Bilanço, Geciken Yüzdelik, Tahsilat, Maaşlar vs. (19 rapor)
- [x] `get_student_exam_analysis(st_id)` — sınav birleştirme + konu analizi (en değerli veri)
- [x] `student_exam_analysis` DB tablosu — ham puan, yerleşme, ÖSYM sıralama, ders netleri, öncelikli konular
- [x] Agent `get_student_analytics`'e exam_analysis entegrasyonu eklendi

## Tamamlanan Görevler (08 Nisan 2026 — Oturum 4: Yerel LLM)

- [x] `llm_router.py` oluşturuldu — LLM soyutlama katmanı (Ollama/Claude hibrit)
- [x] Ollama entegrasyonu: llama3 8B Q4_0, Türkçe çalışıyor, ~2s yanıt
- [x] `fermat_core_agent.py` hibrit routing — basit mesajlar Ollama, tool-calling Claude API
- [x] `intent_parser.py` Ollama entegrasyonu — intent analizi yerel LLM ile (fallback: Claude)
- [x] `.env` güncellendi: LLM_PROVIDER=hybrid, OLLAMA_URL, OLLAMA_MODEL
- [x] Canli test: "merhaba" → Ollama (0 TL), "etut yaz" → Claude API (tool-calling)
- [x] 18/18 sistem testi geçti
- [x] Toplu sınav analizi: 99 öğrenci cekildi (26 sinav verisi yok — normal)
- [x] `scrape_exam_analysis.py` + `scrape_exam_missing.py` — toplu ve eksik öğrenci scraper
- [x] Ollama prompt tuning — kısa/öz Türkçe yanıtlar (~0.8s, ~120 char)
- [x] Port çakışması çözüldü: WP Bridge → 8001 (ChromaDB 8000 kullanıyor)
- [x] `get_daily_etut()` canlı test başarılı — 12 etüt çekildi
- [x] Toplu sınav analizi: 99 öğrenci cekildi (26 sinav verisi yok — normal)
- [x] `scrape_exam_analysis.py` + `scrape_exam_missing.py` — toplu ve eksik öğrenci scraper
- [x] Ollama prompt tuning — kısa/öz Türkçe yanıtlar (~0.8s, ~120 char)
- [x] Port çakışması çözüldü: WP Bridge → 8001 (ChromaDB 8000 kullanıyor)
- [x] TextBlock format fix — history'ye temiz string kaydediliyor
- [x] Sınıf eşleştirme fix — 98 öğrencinin class_name güncellendi (devre+kur'dan)
- [x] İstatistik aracı — "kaç öğrenci var" sorusuna cevap (125 öğrenci + devre dağılımı)
- [x] `get_class_plan` aracı — ders programı + günlük etüt + çakışma kontrolü
- [x] Agent prompt — veri sunumu zenginleştirme + çakışma kontrolü kuralları
- [x] Intent parser Ollama JSON iyileştirme

## Tamamlanan Görevler (08 Nisan 2026 — Oturum 5: Veri Zenginleştirme + Otonom Altyapi)

- [x] Ogretmen ders programi scrape: 14 ogretmen, 249 slot (teacher_timetable DB tablosu)
- [x] Sinif ders programi scrape: 13 sinif, 249 slot (class_timetable DB tablosu)
- [x] Excel export yontemi kesfedildi — sayfa gezme yerine tek tikla toplu veri cekimi
- [x] Etut gecmisi Excel import: 2421 kayit, Eylul 2025 - Mayis 2026 (etut_history DB tablosu)
- [x] Rehberlik notlari Excel import: 1631 kayit (counsellor_notes DB tablosu)
- [x] Devamsizlik sayisi Excel import: 119 ogrenci (devamsizlik_sayisi DB tablosu)
- [x] `import_etut_excel.py` — etut Excel → PostgreSQL importer
- [x] `import_rehberlik_excel.py` — rehberlik notu Excel → PostgreSQL importer
- [x] `import_all_excel.py` — genel Excel importer (devamsizlik + gelecek exportlar)
- [x] `session_keeper.py` — 5dk periyodla Eyotek session canli tutma + WP bildirim
- [x] `fermat_start.py` — tek dosya baslat: session kontrol + WP bridge + session keeper
- [x] WP admin komutlari: "eyotek tamam", "sistem durum", "sync baslat"
- [x] Eyotek erisim kontrolu: session offline iken yazma islemleri engellenir, yerel cache devam
- [x] Davranis Ara kesfedildi — su an veri yok (henuz girilmemis)
- [x] Yoklama Kontrol kesfedildi — gun bazli ders yoklamasi (Excel buyuk, timeout)
- [x] btnPrintExcel buton ID kesfedildi — tum sayfalarda Excel export icin
- [x] `analytics_cache.py` — 9 kategori onceden hesaplanmis cache (ogretmen, etut, devamsizlik vb.)
- [x] `query_analytics` araci — Agent SQL sorgulariyla tum tablolara erisebiliyor
- [x] Cache-first strateji: use_cache parametresi ile DB'ye gitmeden aninda cevap
- [x] DB connection pool: her sorguda baglan/kapat yerine hazir havuz
- [x] Debug loglari gizlendi — kullanici temiz cikti goruyor + dosyaya tam log
- [x] "Dusunuyor..." bekleme animasyonu
- [x] Terminal admin yetkisi — ACL engeli cozuldu
- [x] Tablo kolon isimlari dogru tanimlandi (first_name, full_name vs)
- [x] WP admin komutlari: "eyotek tamam", "sistem durum", "sync baslat"
- [x] Ollama routing iyilestirmesi — analitik sorular otomatik Claude API'ye yonleniyor

## Yeni Dosya Envanteri (eyotek_agent/)

| Dosya | Rol |
|-------|-----|
| `session_keeper.py` | Eyotek session canli tutma + drop algisi + WP admin bildirim |
| `fermat_start.py` | Tek dosya baslat — session + WP bridge + keeper otonom |
| `import_etut_excel.py` | Etut Ara Excel → PostgreSQL etut_history |
| `import_rehberlik_excel.py` | Rehberlik Notu Excel → PostgreSQL counsellor_notes |
| `import_all_excel.py` | Genel Excel importer (devamsizlik + gelecek) |
| `scrape_timetables.py` | Ogretmen + sinif ders programi scraper |
| `analytics_cache.py` | Onceden hesaplanmis analitik cache (10 kategori, 1 saat gecerli) |
| `fast_responses.py` | Hizli yanit motoru: ogrenci+ogretmen sik sorulari <5ms, Claude API gereksiz |
| `build_topic_tracker.py` | Sinav verisinden ogrenci zayif konu listesi olustur |
| `usage_tracker.py` | Kullanim loglama: mesaj, kullanici, token, yanit suresi, gunluk ozet |
| `import_exam_details.py` | Sinav JSON → PostgreSQL student_exams (sinav bazli detay) |

## Yeni PostgreSQL Tablolari

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| etut_history | 2421 | Tum etut kayitlari (Eylul 2025 - Mayis 2026), tarihli |
| counsellor_notes | 1631 | Rehberlik gorusme notlari, ogrenci bazli |
| devamsizlik_sayisi | 119 | Toplam devamsizlik saati, ogrenci bazli |
| teacher_timetable | 249 | Ogretmen haftalik ders programi |
| class_timetable | 249 | Sinif haftalik ders programi |
| student_exams | 3631 | Sinav bazli detay: tarih, ders netleri, 99 ogrenci (Agu 2025 - Nis 2026) |
| student_topic_tracker | 1145 | Ogrenci konu takibi: zayif konular, calisma durumu, siralama |
| student_insights | 0 | Konusmalardan cikarilan anlamlar: duygu, motivasyon, kaygi, ilgi alani |
| usage_log | 0 | Her mesaj: kim, ne zaman, hangi kaynaktan, kac ms, kac token |
| daily_stats | 0 | Gunluk ozet: mesaj, kullanici, rol dagilimi, maliyet |
| blocked_numbers | 0 | Neo tarafindan bloklanan numaralar |

## Otonom Calisma Modeli

```
Sabah 1x: python fermat_start.py
  → Eyotek'e giris (manuel captcha) → ENTER
  → WP Bridge online (port 8001)
  → Session Keeper baslar (5dk periyod)
  → 7/24 otonom calisma

Session duserse:
  → WP ile admin'e bildirim
  → Admin telefondan "eyotek tamam" yazar
  → Sistem Chrome'dan taze cookie alir
  → Online devam eder

Eyotek offline iken:
  → WP chatbot yerel cache'ten cevap verir
  → Yazma islemleri engellenir (guvenlik)
  → Okuma sorulari (profil, sinav, etut) cevaplanir
```

## WP Admin Komutlari

| Komut | Islem |
|-------|-------|
| `eyotek tamam` | Session yenile (Chrome CDP'den cookie al) |
| `sistem durum` | Eyotek status, uptime, son kontrol |
| `sync baslat` | Veri senkronizasyonu tetikle |
| `sifirla` | Konusma gecmisi temizle |

## Yetki Matrisi (Kurumsal Guvenlik — Delinmez)

### Rol Hiyerarsisi
```
NEO (Zeki Goksal - 905051256802) — Mimar. Sistem efendisi.
  ├── Tum yetkiler + sistem yonetimi
  ├── WP'den: blokla/blok kaldir, yetki degistir, sistem durumu
  └── Kod degisikligi, otomasyon genisletme

MUDUR (Mahsum Yalcin - 905462605446, Duygu Goksal - 905051256801)
  ├── Tum ogretmen ve ogrenci verileri (finans HARIC)
  ├── Kapsamli raporlar, analizler
  └── Etut yazma, rehberlik notu

OGRETMEN (staff tablosundan, numaralar ileride eklenecek)
  ├── Kendi sinifi, kendi etutleri
  └── YASAK: telefon, odeme, baska ogretmen kisisel

OGRENCI (117 kayitli numara)
  ├── Sadece kendi verisi — sinirsiz akademik dialog
  └── YASAK: baska ogrenci, ogretmen bilgisi, kurum verisi
```

| Veri/Islem | Admin | Mudur | Ogretmen | Rehber | Ogrenci | Veli |
|------------|-------|-------|----------|--------|---------|------|
| Tum ogrenci listesi | OK | OK | Kendi sinifi | OK | YASAK | YASAK |
| Ogrenci sinav verisi | OK | OK | Kendi sinifi | OK | Sadece kendi | Sadece cocugu |
| Ogrenci devamsizlik | OK | OK | Kendi sinifi | OK | Sadece kendi | Sadece cocugu |
| Ogrenci telefon/veli | OK | OK | YASAK | YASAK | YASAK | YASAK |
| Odeme/borc bilgisi | OK | OK | YASAK | YASAK | YASAK | YASAK |
| Ogretmen kisisel bilgi | OK | OK | YASAK | YASAK | YASAK | YASAK |
| Maas/muhasebe | OK | YASAK | YASAK | YASAK | YASAK | YASAK |
| Etut yazma | OK | OK | OK | OK | YASAK (talep eder) | YASAK |
| SMS gonderme | OK | OK | YASAK | YASAK | YASAK | YASAK |
| Rehberlik notu | OK | OK | OK | OK | YASAK | YASAK |
| query_analytics SQL | OK | OK | Filtreli | Filtreli | Kendi soz_no | YASAK |

### Guvenlik Katmanlari
1. **Telefon = Kimlik**: Rol WP numarasindan otomatik belirlenir, degistirilemez
2. **ACL Matrix**: Arac bazli izin kontrolu (kod seviyesi)
3. **SQL ACL**: query_analytics sorgularinda tablo/kolon filtresi
4. **Fast Response ACL**: Hizli yanit motorunda baska ogrenci adi kontrolu
5. **LLM Prompt ACL**: System prompt'ta yetki kurallari (son savunma hatti)
6. **Bilinmeyen Numara Engeli**: Kayitsiz numaralar sisteme giremez
7. **Flood Koruma**: 30+ mesaj/dk = 1 saat otomatik ban
8. **Neo Komutlari**: Sadece admin WP'den blokla/yetki degistir/sistem durumu

## Neo (Mimar) WP Komutlari

| Komut | Islem |
|-------|-------|
| `blokla 905xxxxxxxxx` | Numarayi blokla (mesaj almaz) |
| `blok kaldir 905xxxxxxxxx` | Bloku kaldır |
| `yetki 905xx ogretmen` | Rol degistir (admin/mudur/ogretmen/ogrenci) |
| `sistem` | Sistem durumu raporu |
| `rapor` | Gunluk kullanim raporu (mesaj, kullanici, token, kaynak dagilimi) |
| `trend` | Haftalik kullanim trendi |
| `eyotek tamam` | Session yenile |

## WP Etkilesim Mimarisi (Jarvis Vizyonu)

### Ogrenci Deneyimi (Telefon = Kimlik)
```
Ali (WP) → FermatAI
  ├── Kimlik: telefon numarasi → students.phone → soz_no → profil
  ├── Yetki: SADECE kendi verisi (sinav, devamsizlik, etut, ders programi)
  ├── Yasak: kurum, personel, diger ogrenciler bilgisi
  └── Sinirsiz: kendi akademik verisinde tam dialog
       ├── "Son 3 denememi kiyasla" → student_exams tablosu
       ├── "Ders calisma programi yap" → topic_tracker + timetable
       ├── "Kaldirma kuvvetini anlamiyorum" → kavram aciklamasi (LLM)
       ├── "Bu soruyu nasil cozerim?" (foto) → Vision API
       └── "Fizik etudu istiyorum" → eskalasyon
```

### Eskalasyon Akisi
```
Ogrenci: "Fizik etudu istiyorum"
  → Sistem: topic_tracker'dan zayif konu belirle
  → Sistem: teacher_timetable'dan uygun ogretmen+saat bul
  → Sistem → Ogretmene WP rapor:
     "Ali fizik etudu talep etti. Kaldirma kuvveti eksik.
      Son 3 deneme fizik: 1.25→8.75→7.0. Persembe 14:00 bos."
  → Ogretmen WP'den: "Persembe 14:00'a yaz"
  → Sistem → Eyotek'te etut yazar
  → Sistem → Ali'ye bilgi: "Persembe 14:00 fizik etudun planlandi"
  → Sistem → timetable cache guncelle (doluluk degisti)
```

### Ogretmen Deneyimi
```
Kardelen Hoca (WP) → FermatAI
  ├── Kendi siniflarini sorgula
  ├── "Su ogrenciye etut yaz" → Eyotek yazma
  ├── Gun sonu topluca bilgi notlari (ogrenci talepleri)
  └── Ogrenci eskalasyonlarina yanit ver
```

### Pedagojik Zeka Dongusu
```
Konusma → Anlam Cikarma → Profil Guncelleme → Sonraki Konusmada Kullanma
  ├── Ogrenci 3 gun "stresli" → student_insights → rehber ogretmene bildirim
  ├── Ogrenci "calisdim" → topic_tracker → siradaki konu
  ├── Deneme sonucu geldi → "Bak bu soruyu kacirmadiniz!" cikarimidir
  └── Etut yazildi → timetable cache guncelle → sonraki oneri guncel
```

### Veri Guncelleme Kurali
- Etut yazildiginda → cache yenile (doluluk degisti)
- Yeni deneme cekildiginde → student_exams + topic_tracker guncelle
- Konusma sonrasi → student_insights otomatik analiz
- Sistem her zaman en guncel veriyle calisir

## WP API Medya Yetenekleri

| Mesaj Tipi | Durum | Detay |
|------------|-------|-------|
| Yazi | AKTIF | Ana iletisim kanali |
| Ses/Voice | AKTIF | Whisper ASR ile transkripsiyon |
| Fotograf | AKTIF | Claude Vision ile soru cozum (Kunduz benzeri) |
| Video | KAPALI | Gereksiz islem gucu, akademik degeri dusuk |
| Dokuman | KAPALI | Ileride PDF soru cozum eklenebilir |
| Sticker | YOKSAY | Yanit verilmez |

### Foto Soru Cozum Sistemi
- Ogrenci soru fotografi atar → Claude Vision analiz eder → adim adim cozum doner
- Gunluk limit: **10 foto/ogrenci** (Neo direktif 9 May, 3 → 10; aktif ogrenci +3 = 13)
- Maliyet: ~$0.02/foto (Claude Sonnet Vision)
- 125 ogrenci × ~10 foto/gun max = ~$25/gun teorik tavan (pratik ~$8-12)
- Model: claude-sonnet (hiz/maliyet dengesi)

## Tamamlanan Gorevler (10 Nisan 2026 — Oturum 6: Paraphrase Coverage + Kalite)

- [x] 173 paraphrased soru testi yazildi (`test_paraphrase_coverage.py`)
- [x] Fast response coverage: %85 → %100 (26 yeni pattern eklendi)
- [x] LLM Router fix: "ders programim", "sinif dagilimi", "etut istatistigi" artik cloud'a gidiyor
- [x] Imla hatali sorgular testi: "sinav sonucum", "devamsizligim kac", "calisma plani yap" hepsi calisiyor
- [x] Ollama halusinasyon guvenlik agi: veri sorusuna sayi iceren cevap → otomatik Claude'a eskalasyon
- [x] Gorsel kalite iyilestirmesi: devamsizlik, guclu konular cevaplari emoji+bold+liste ile zenginlestirildi
- [x] OGRENCI_PATTERNS genisletildi: gidisat, netlerim artiyor, nerede hata, neleri bilmiyorum, programim ne
- [x] OGRETMEN_PATTERNS genisletildi: programim ne, haftalik ders saati, etut istatistigi/performansi
- [x] _CLOUD_KEYWORDS genisletildi: program, deneme, sonuc, konular, calismam, performans, durum, istatisti
- [x] Selamlama pattern: "iyi gunler" artik tum rollerde fast_response ile yakalaniyor

## Tamamlanan Gorevler (10 Nisan 2026 — Oturum 7: No-Data Graceful + Gorsel Kalite)

- [x] No-data graceful test: 21 senaryo (veri yok durumunda stratejik cevap kontrolu)
- [x] Sinav/konu verisi olmayan ogrenci cevaplari: D-grade → A-grade (emoji+bold+yonlendirme)
- [x] "henuz sinav verimiz yok" → pedagogik ton + alternatif onerme + karsi soru
- [x] "konu analizi verisi yok" → "denemelere katildikca otomatik belirlenecek" + yonlendirme
- [x] "rehberlik gorusme kaydimiz yok" → destek tonu + planlama onerisi
- [x] Anlamsiz kisa mesajlar (ok/hmm/./tamam/asdfghjkl) → karsi soru + menu gosterme
- [x] Tek nokta/sembol mesajlari → clarification template (CLARIFICATION_TEMPLATES)
- [x] Onay kelimeleri (tamam/ok/evet) → isimle hitap + yardim menusu
- [x] Anlamsiz harf dizisi tespiti: sesli harf orani < %20 → "mesajini anlayamadim" + ornekler
- [x] Admin kurum ozeti gorsel: emoji kategoriler (ogrenci, personel, etut, rehberlik)
- [x] En basarili ogrenci gorsel: medalya emojileri + bold puan
- [x] Devamsizlik listesi gorsel: renk kodlu (kirmizi/sari/yesil) + bold saat
- [x] Calisma plani gorsel: renk kodlu konular + emoji basliklar
- [x] Hedef analizi gorsel: emoji + bold + yonlendirici kapatis
- [x] YASAK kelime testi: teknik hata, LLM sızıntısı, kotu UX kelimeleri — 0 ihlal

## Tamamlanan Gorevler (10 Nisan 2026 — Oturum 8: Ollama Kalite Kontrolu)

- [x] 16 gercek Ollama yaniti test edildi — 16/16 A-grade
- [x] Ollama system prompt'a arayan ismi baskin sekilde eklendi (prompt basina)
- [x] Uygunsuz icerik filtresi eklendi (fermat_core_agent.py eskalasyon)
- [x] Ingilizce false positive duzeltildi (can, her, an gibi Turkce isimler haric)
- [x] Ortalama Ollama yanit suresi: 2.7s (kabul edilebilir)
- [x] Konu aciklama kalitesi: fizik/mat/bio/tarih/turkce — hepsi A-grade
- [x] Motivasyon/sohbet kalitesi: pedagogik ton, soru soruyor, yonlendiriyor
- [x] 4 test dosyasi toplam 269+ soru: %100 basari

## Tamamlanan Gorevler (10 Nisan 2026 — Oturum 9: Edge Case + Production Stabilite)

- [x] 44 edge case stress test: sacmalik, emoji, injection, kufur, karisik dil — 44/44
- [x] Kufur/argo → fast_response ile aninda kurumsal yanit (Ollama'ya ASLA dusmez)
- [x] Sistem sikayeti → geri bildirim tonu + kayit mekanizmasi
- [x] Emoji-only / sayi-only → fast_response ile yonlendirme
- [x] Kurum bilgisi (fermat nedir, fark, avantaj) → Claude'a yonlendirme
- [x] Hassas konular (intihar, depresyon, bunalim) → Claude'a yonlendirme
- [x] Ollama scope daralma: %41 → %20 (sadece akademik konu + basit sohbet)
- [x] _fix_ollama_name post-processing: 13/13 isim duzeltme basarili
- [x] routing_stats DB tablosu: her mesajin kaynak/sure/rol takibi
- [x] 5 test paketi toplam 313 soru: HEPSI %100
- [x] Final stabilite testi: 27/27 — production hazir

## Routing Dagilimi (Hedef vs Gercek)

**NOT — Oturum 24 sonrasi:** VPS'te Ollama yok, Groq 70B onun yerini aldi. Guncel hedef:

| Kaynak | Yeni Hedef (VPS) | Aciklama |
|--------|-----------------|----------|
| Fast Response | %45 | Selamlama, sablonlu sorgu, guvenlik |
| Groq 70B | %30 | Kavramsal + sohbet + (aktive edilirse) safe tool |
| Claude API | %25 | Hassas, yazma, analiz, duygu/kriz |
| Ollama | %0 (laptop %20) | VPS'te yok; laptop dev'de fallback |

Eski (laptop Ollama) tarihi hedefi: Fast %50+ / Claude %30 / Ollama %20.

## Yeni PostgreSQL Tablolari

| Tablo | Aciklama |
|-------|----------|
| routing_stats | Her mesajin kaynak (fast/ollama/claude), sure (ms), rol takibi |

## Tamamlanan Gorevler (11 Nisan 2026 — Oturum 10: Hafiza + Rapor + Duygu)

- [x] `conversation_memory.py` — ogrenci bazli context cache (son deneme, konu, duygu, devamsizlik)
- [x] `build_context_prompt()` — Claude system prompt'a ogrenci baglami ekleme
- [x] `daily_report.py` — gunluk otomatik rapor: kullanim, aktif ogrenciler, riskli sinyaller, maliyet
- [x] Zamanlanmis gorev: her gun 20:03'te admin'e WP rapor
- [x] `sentiment_tracker.py` — duygu analizi: crisis/stressed/negative/angry/positive/neutral
- [x] 9 duygu pattern kategorisi: stres, kaygi, motivasyon dusuk, intihar, ofke...
- [x] `student_insights` tablosuna otomatik kayit (her mesaj sonrasi)
- [x] `check_and_alert_rehber()` — 7 gunde 3+ negatif sinyal → rehber uyari raporu
- [x] Ollama `re` import bug duzeltildi — Ollama artik calisiyor (%0 → %20)
- [x] Prompt injection fast_response ile yakalama (26x spam → 0 token)
- [x] "not et" hack filtresi — sacma talimatlar engelleniyor
- [x] "bomba nasil yapilir" gibi tehlikeli icerik fast_response ile engel
- [x] "ITU istiyorummm" motivasyon/hedef karisma fix
- [x] "deneme analizi" fast_response pattern eklendi
- [x] Ollama gorsel kalite: --- ayirici, *bold* baslik, _italik_ kapatis zorunlu

## Yeni Dosyalar (Oturum 10)

| Dosya | Rol |
|-------|-----|
| `conversation_memory.py` | Ogrenci bazli context cache + prompt eklentisi |
| `daily_report.py` | Gunluk otomatik rapor olusturma + WP gonderme |
| `sentiment_tracker.py` | Duygu analizi + rehber bildirim sistemi |
| `motivation_library.py` | 8 sohbet + 8 motivasyon sablonu kutuphanesi |

## Tamamlanan Gorevler (12 Nisan 2026 — Oturum 11: Kalite + Import + Izleme)

- [x] Konusma analizi: 6 sorun tespit ve duzeltme (veda, motivasyon false positive, Ollama format)
- [x] Veda/kapanış pattern'ları: bye, hoşça, görüşürüz, yok sağol canım — tum uzunluklarda
- [x] Motivasyon false positive fix: "bırak" → "bırak ders" spesifikleştirildi
- [x] Ollama WhatsApp format yasak listesi: ### YASAK, ** YASAK, kod blogu YASAK
- [x] Frustration escalation: 3 kez "yanlış anladın" → Claude üst hakem
- [x] `auto_import_exams.py` — Excel → DB otomatik import (imports/ klasörü)
- [x] `quality_monitor.py` — routing dağılımı, frustration, tekrar, Ollama kalite izleme
- [x] `ollama_arbiter.py` — belirsiz mesajlarda Ollama hakem (0.5s, $0)
- [x] YKS/LGS müfredat bilgisi sisteme eklendi (TYT 120, AYT 80, LGS 90 soru)
- [x] Maarif Modeli ayrımı: 2026 YKS = eski müfredat, 2028 = yeni
- [x] Claude üst hakem talimatı: "Haklısın, yanlış anlamıştım" → düzelt → devam et
- [x] Foto soru çözüm false positive fix: process_message bypass → direkt gönderim
- [x] Günlük Claude limiti 300'e düşürüldü (maliyet kontrolü)
- [x] Cloud keyword'ler daraltıldı: "durum/neden/bilmiyorum" kaldırıldı (Ollama alanı genişledi)

## Yeni Dosyalar (Oturum 11)

| Dosya | Rol |
|-------|-----|
| `ollama_arbiter.py` | Belirsiz mesajlarda Ollama niyet analizi (hakem) |
| `auto_import_exams.py` | Excel → DB otomatik deneme import |
| `sync_exams.py` | Eyotek'ten TYT+AYT sinav verilerini otomatik cekme (tum ogrenciler) |
| `weekly_sync.py` | Haftalik sync kontrol + cache yenileme |
| `quality_monitor.py` | Konuşma kalitesi otomatik izleme raporu |

## Tamamlanan Gorevler (12 Nisan 2026 — Oturum 12: Veri + Sync + Premium)

### Veri Guncelleme (dev adim)
- [x] TYT net: 999 → 2.310 (+1.311 kayit, %131 artis)
- [x] AYT net: 0 → 193 (sifirdan olusturuldu)
- [x] Konu takibi: 1.145 → 2.338 (+1.193)
- [x] Toplam sinav: 2.828 kayit, 116 ogrenci
- [x] Sinav istatistik sayfasi kesfi — toplu net cekimi (990 kayit tek seferde)
- [x] `fill_missing_nets.py` — sinav bazli toplu net doldurma
- [x] `sync_exams.py` — TYT+AYT birlikte otomatik cekme
- [x] `smart_sync.py` — incremental sync (tracking + resume + WP bildirim)
- [x] `post_sync_update.py` — sync sonrasi konu takibi + cache yenileme
- [x] `scrape_exam_stats.py` — sinav istatistik sayfasindan toplu veri

### Konusma Analizi + Duzeltmeler
- [x] Ecrin AYT/TYT karisikligi: Claude prompt'a `[AYT]%` filtre
- [x] Mahsum "notunu dus" → gun programi yerine Claude devamsizlik analizi
- [x] "token" komutu → admin WA token yenileme (Ollama halusilasyon engellendi)
- [x] SMS/WP karisikligi → prompt'a "SMS DEGIL WP" kurali
- [x] Ollama post-processing: kontrol karakter + yarim cumle kirpma
- [x] Frustration pattern genisleme: "neden cevap vermedin"
- [x] WP profil fotografı guncellendi (API ile)

### Yeni Sistemler
- [x] `secure_messenger.py` — guvenli WP mesaj gonderim (onay + hedef dogrulama + log)
- [x] `admin_sync_commands.py` — WP'den guncelle/son guncelleme/guncelle [isim]
- [x] `sync_tracking` tablosu — ogrenci bazli sync durumu
- [x] `fill_missing_nets.py` — sinav istatistik sayfasindan toplu net
- [x] Premium yonetim segmenti — Bilge + Murathan ozel karakter profilleri + diyalog tarzı
- [x] Murathan arkadasca profil: pilot referansları, ODTU bagi, diyalog odakli, soru soran
- [x] Yonetim kisa onay mesajlari (tabii/evet) → Claude baglam koruma
- [x] Uzun mesajlar (80+ char) yonetim/mudur → Claude premium kalite
- [x] "en basarili" + grafik/trend istegi → Claude analiz (Murathan fix)
- [x] Admin komutlari: token, son guncelleme, guncelle, sync durumu

## Tamamlanan Gorevler (13 Nisan 2026 — Oturum 15: pgvector + RAG + Alarm Sistemi)

### Session Keeper CDP Fix
- [x] `session_keeper.py` — CDP tabanlı gerçek sayfa yenileme (HTTP GET yerine)
- [x] `_cdp_keep_alive()` — Chrome tab üzerinden Eyotek session yenileme
- [x] `_try_cookie_refresh()` — Login sayfasına düşünce otomatik cookie yenileme
- [x] `check_session()` — CDP ile session kontrol (fallback HTTP)
- [x] `notify_admin()` — Direkt Graph API ile WP bildirim (bridge bağımsız)
- [x] CHECK_INTERVAL 5dk → 3dk (session timeout ~20-30dk)
- [x] Test: CDP keep-alive OK, 8 cookie güncellendi

### Konuşma Analizi Düzeltmeleri
- [x] Claude system prompt: "HER ZAMAN TURKCE yaz, Ingilizce YASAK" kuralı
- [x] Selamlama + soru birlikte gelince (30+ char) → Claude'a yönlendir
- [x] Tek kelimelik mesajlara boş menü gösterme kuralı

### PDF Import Pipeline
- [x] `pdf_importer.py` — PDF → metin → chunk → embedding → pgvector
- [x] PyMuPDF (fitz) ile metin çıkarma
- [x] Akıllı chunking: paragraf bazlı, overlap ile bağlam koruma
- [x] Ders/konu otomatik tespiti (keyword analizi)
- [x] `kaynaklar/akademik/` ve `kaynaklar/pedagojik/` klasör yapısı
- [x] Tek dosya veya klasör import desteği

### MEB OGM Materyal Scraping
- [x] `ogm_scraper.py` — MEB sitesinden otomatik PDF indirme + RAG import
- [x] Site yapısı tam haritalandı: 12 YKS Hazırlık alt menüsü
- [x] TYT 8 ders konu özeti indirildi (380MB, 985 chunk RAG'a eklendi)
- [x] URL pattern keşfedildi: `/mebi-ozet-indir?id={id}` → direkt PDF
- [x] Çıkmış soru kitapları 7 PDF indirildi (155MB) + RAG import
- [x] MEBİ tarama testleri 17 PDF indirildi (143MB) + RAG import
- [x] Toplam indirilen: 32 PDF, ~675MB MEB resmi içerik
- [x] RAG toplam: 4000+ kayıt (büyümeye devam)

### OGM Vision Import (Çıkmış Sorular)
- [x] `ogm_vision_importer.py` — sayfa JPG → Claude Vision → yapılandırılmış soru metni → RAG
- [x] Kitap yapısı keşfedildi: CDN'den direkt JPG, `ogm-small-cdn.eba.gov.tr/ogm-test-images/{id}/pages/{n}.jpg`
- [x] Pilot test başarılı: 1 sayfa → 4 soru tam metin + şıklar + görsel açıklama ($0.02)
- [x] 7 kitap tanımlandı (YDT hariç 6'sı kullanılacak):
  - TYT: `68b4f2b4eb079be0e77092ba` (Türkçe, Mat, Fen, Sosyal)
  - AYT Sayısal: `68b4eb6deb079be0e7709222` (Mat, Fiz, Kim, Bio) — IMPORT BAŞLADI
  - AYT EA: `68b1eedc7061abc463473e6b` (TDE, Tarih, Coğ, Mat)
  - AYT Sözel: `68b23238eb079be0e76eea27` (TDE, Tarih, Coğ, Felsefe, Sosyoloji)
  - TYT Din Kültürü: `68d3a84fdbcaa9db10a16a1b`
  - AYT Sözel-2: `68d39ea3dbcaa9db10a1596a` (Din Kültürü)
  - YDT İngilizce: `68b4cbcdeb079be0e77080c9` — ATLA (YDT sınıfı yok)
- [ ] Toplam tahmini maliyet: 6 kitap × ~200 sayfa × $0.02 = ~$24

### Alarm & Bildirim Sistemi
- [x] `alert_system.py` — merkezi alarm yonetimi (ALERTS_ACTIVE=False, Neo aktif diyene kadar kapali)
- [x] Alarm 1: Net dusus — 2+ ardisik deneme dusus (-8 net esik), 4 kritik ogrenci tespit
- [x] Alarm 2: Devamsizlik — 100+ saat uyari, 200+ saat kritik, 32 ogrenci tespit
- [x] Alarm 3: Duygu/kriz sinyali — 7 gunde 3+ negatif sinyal
- [x] Haftalik kurum ozeti — kullanim, en aktif, deneme trendi, risk sinyalleri
- [x] `alert_log` DB tablosu — tum alarm gecmisi kaydediliyor
- [x] Spam onleme: her turden max 5 gosterim, yuksek esikler, tolerans
- [x] Calisma plani ZORUNLU veri cekme kurali guclendirildi (bos plan onlendi)

### RAG Altyapı
- [x] pgvector v0.8.0 kuruldu (Docker PostgreSQL container'a build + install)
- [x] nomic-embed-text embedding modeli indirildi (768 boyut, Türkçe destekli, yerel $0)
- [x] `rag_content` tablosu oluşturuldu (sinav_turu, ders, konu, icerik, embedding vector(768))
- [x] `rag_engine.py` — embed/search/add fonksiyonları (semantik arama, cosine similarity)

### İçerik Üretimi
- [x] 36 YKS konu anlatımı üretildi (Claude Sonnet, ~$0.72)
- [x] Dağılım: Matematik 16, Türkçe 13, Geometri 5, Fizik 1, Tarih 1
- [x] Her içerik: konu özeti + formüller + soru tipleri + çalışma yöntemi + dikkat noktaları
- [x] Öncelik: öğrenci zayıf konularından (en çok hata yapılan 35 konu)
- [x] `rag_content_builder.py` — DB'den öncelikli konu tespiti + Claude ile üretim + pgvector'e kayıt

### Claude Entegrasyonu
- [x] `search_curriculum` tool tanımı eklendi — semantik müfredat araması
- [x] ACL: öğrenci rolü search_curriculum kullanabiliyor
- [x] System prompt: KONU ANLATIMI PROTOKOLÜ eklendi (RAG → kişiselleştir → soru sor)
- [x] LLM Router: "nedir/açıkla/formül/nasıl çözülür" → Claude'a yönlendirildi (RAG kullanacak)
- [x] Semantik arama kalitesi: 9/10 doğru eşleşme (ortalama skor 0.67)

### YKS Tarih/Geri Sayım
- [x] "YKS'ye kaç gün kaldı" → fast response (TYT: 61 gün, AYT: 62 gün)
- [x] "TYT ne zaman" → 13 Haziran 2026 + geri sayım
- [x] "LGS ne zaman" → 7 Haziran 2026 + geri sayım

## Yeni Dosyalar (Oturum 15)

| Dosya | Rol |
|-------|-----|
| `rag_engine.py` | pgvector semantik arama motoru (embed/search/add) |
| `rag_content_builder.py` | Claude ile YKS konu anlatımı üretici |

## Yeni PostgreSQL Tablolari

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| rag_content | 36 | YKS müfredat bilgi bankası (konu anlatımı + embedding) |

## Tamamlanan Gorevler (12 Nisan 2026 — Oturum 14: Konusma Analizi + Calisma Plani Pro)

### Konusma Analizi (48 saat, 12 kullanici, 300+ mesaj)
- [x] KRITIK: "hesapla" → `sapla` tehdit false positive duzeltildi (`\bsapla\b` word boundary)
- [x] KRITIK: `[FOTO SORU COZUM]` mesajlari tehdit filtresini bypass ediyor
- [x] Damla foto soru hakki yanlis bilgi ("sinirsiz" → "3/gun") — `foto_hakki` fast response eklendi
- [x] Mahsum "notunu dus" → program gosterme sorunu — Claude system prompt kurali eklendi
- [x] Zehra tekrarlayan calisma plani template — Claude system prompt "2. kez sorma" kurali
- [x] Zeynep veda sonrasi devam etme — "sagol/bye sonrasi konu acma" kurali
- [x] DB sinav isimleri duzeltildi: 20 kayit "Sinav 999000095" → gercek isim
- [x] `fill_missing_nets.py` fallback iyilestirme — ayni tarihteki baska ogrenciden isim al
- [x] `conversation_viewer.py` — WhatsApp tarzi HTML konusma paneli (47 kisi, 3174 mesaj)

### Profesyonel Calisma Plani Sistemi
- [x] `study_plan_builder.py` — zengin veri paketi: 11 veri katmani (zayif konu, trend, hedef, potansiyel, ders programi)
- [x] `build_study_plan_context` tool — Claude'a tek cagriyla tum akademik veri
- [x] Claude system prompt: 4 adimli Calisma Plani Protokolu (veri topla → analiz sun → soru sor → detayli plan)
- [x] Fast response routing: "calisma plani yap" → Claude'a (eski basit template kaldirildi)
- [x] student_scenarios.py: eski 3 sorulu generic template kaldirildi
- [x] Her gun icin ders+konu+sure+yontem+gerekce formati zorunlu
- [x] Net kazanim potansiyeli analizi (hangi derste kac net kazanilabilir)
- [x] 3 profil test: guclu (Ecrin), orta (Mehmet Alp), LGS (Ada) — hepsi CLAUDE'a gidiyor

### Veri Guncelleme
- [x] LGS sinav sekmesi kesfedildi — 5 ogrenci LGS neti cekildi
- [x] `sync_missing_students.py` — dropdown menu acma + LGS/TYT otomatik sekme secimi
- [x] Sinav verisi kapsami: 102 → 107/125 ogrenci

## Yeni Dosyalar (Oturum 14)

| Dosya | Rol |
|-------|-----|
| `study_plan_builder.py` | Calisma plani icin zengin veri paketi (11 katman) |
| `conversation_viewer.py` | WhatsApp tarzi HTML konusma paneli |
| `sync_missing_students.py` | Eksik ogrenci sinav verisi cekimi (LGS destekli) |

## Tamamlanan Gorevler (12 Nisan 2026 — Oturum 13: Context Zenginlestirme)

- [x] `conversation_memory.py` zenginlestirme — zayif konular (top 5, hata>=50%) context'e eklendi
- [x] Son 3 TYT deneme trendi context'e eklendi (deduplicated, toplam>5 filtreli)
- [x] AYT son deneme context'e eklendi
- [x] Trend yon analizi: +3 artis → "tebrik et", -3 dusus → "destekleyici ol"
- [x] Context prompt'a "tool_call YAPMA, cache'den kullan" talimatı eklendi
- [x] `ogrenci_ayt_deneme()` fast response fonksiyonu — AYT sonuclari aninda ($0)
- [x] AYT pattern'lari: ayt deneme/sonuc/netler/nasil → fast response
- [x] AYT zayif konular: "ayt zayif konularim" → fast response
- [x] Ollama arbiter AYT intent eklendi
- [x] 97/117 ogrenci zayif konu context'i, 102/117 deneme trend context'i mevcut
- [x] Entegrasyon testi: 6/7 ogrenci sorusu FAST, context 995 char (optimal)

## Hazir ama Pasif Ozellikler (Neo "aktif et" diyene kadar)

| Ozellik | Dosya | Durum |
|---------|-------|-------|
| Veli Modulu | `veli_module.py` | HAZIR — `VELI_MODULE_ACTIVE = False` |
| PDF Rapor | `pdf_report.py` | HAZIR — `python pdf_report.py <soz_no>` |

## Tamamlanan Gorevler (13-14 Nisan 2026 — Oturum 16: OGM Vision + WP Image + Kalite)

### OGM Vision Import Pipeline
- [x] `ogm_vision_importer.py` v2.0 — retry (3x, 10/20/30s), resume, 5x404 kitap sonu, KITAPLAR dict
- [x] AYT Sayisal import: 149 kayit (s.9-208 tamamlandi)
- [x] TYT import: 202 kayit (s.9-367 tamamlandi)
- [x] AYT EA import: 39 kayit (s.9-203, Matematik sayfalari atlanarak)
- [x] EA akilli tarama — Matematik/Geometri sayfalari AYT Sayisal'da zaten var, skip
- [x] Sozel kitaplar devre disi (AYT Sozel, TYT Din, AYT Sozel-2 — sozel ogrenci yok)
- [x] RAG toplam: 4,482 kayit (390 OGM Vision + 4,092 diger)
- [x] sinav_turu bug fix — TYT kayitlari "AYT" olarak kaydedilmisti, duzeltildi
- [x] 22 duplicate RAG kaydi temizlendi

### WhatsApp Image Gonderme
- [x] `send_wa_image(to, image_url, caption)` — Meta Graph API ile WP image gonderme
- [x] `kaynak_to_cdn_url(kaynak)` — RAG kaynak → CDN URL donusumu (2 format destekli)
- [x] `send_exam_image` tool — Claude tool-calling ile gorsel gonderme
- [x] CDN publick URL: `ogm-small-cdn.eba.gov.tr/ogm-test-images/{id}/pages/{n}.jpg`
- [x] Caption max 1024 char (WP limiti)

### Cikmis Soru Interaktif Sistemi
- [x] `list_exam_questions` tool — konu/ders/yil bazli cikmis soru katalogu
- [x] `sayfadaki_sorular` indeksi — her sonucta soru numarasi + yili
- [x] 2 adimli akis: katalog goster → ogrenci secer → gorsel gonder → birlikte coz
- [x] Ders bazli fast response menu — "fizik cikmis sorular" → aninda katalog
- [x] `get_cikmis_soru_menu()` — DB'den dinamik, TYT/AYT etiketli, yil bazli
- [x] Keyword fallback arama — semantik yetersizse icerik'te text arama
- [x] Turkce karakter varyantlari (turev→turev, hucre→hucre, osmanli→osmanli vb.)
- [x] Ders normalizasyonu — Claude "Turkce" yazsa bile DB'deki "Turkce"ye eslesir

### YKS Konu Dagilimi Referans Verisi
- [x] MEB OGM 2018-2025 gercek konu dagilimi system prompt'a eklendi
- [x] AYT Mat: Limit/Turev ~4, Analitik Geo ~4, Integral ~3, Fonksiyonlar ~3
- [x] AYT Fizik: Kuvvet 5-6, Elektrik/Manyetizma 3-4, Dalga/Optik 1-2
- [x] Proaktif oneri: deneme analizi + zayif konu → "bu konudan her yil X soru cikiyor"

### Rol Bazli Yetenek Tanitimi
- [x] `get_yetenekler(role, name)` — 6 rol icin etkileyici, kurumsal, sci-fi hissiyati
- [x] Ogrenci: "Kisiye Ozel YKS Zeka Motoru" — deneme rontgeni, zayif nokta haritasi
- [x] Ogretmen: "Akilli Ogretmen Asistani" — performans haritasi, sinif karsilastirmasi
- [x] Rehber: "Rehberlik Zeka Motoru" — 360 derece profil, duygu radari
- [x] Mudur/Yonetim: "Kurum Yonetim Zekasi" — anlik kurum fotografi
- [x] Admin: "Merkez Komuta" — tam veri erisimi
- [x] Pattern: "ne yapabilirsin/kabiliyetlerin/yeteneklerin" → fast response 8/8

### Kalite Kontrol ve Duzeltmeler
- [x] `_clean_response`: `**bold**`→`*bold*`, `# baslik`→`*baslik*`, tablo→liste donusumu
- [x] study_plan_builder etut_history ogrenci filtresi eklendi (onceden kurum geneli geliyordu)
- [x] RAG similarity threshold 0.35 + connection pool (asyncpg.create_pool)
- [x] Overlapping fast_response pattern'lari temizlendi (3 duplicate kaldirildi)
- [x] Easter Egg bolumu 80→8 satira kisildi (~2500 token/cagri tasarruf)
- [x] Admin routing: selamlama/yetenek haric tum admin sorgulari Claude'a
- [x] "Not et" admin icin Claude'a (context'ten anlasın)
- [x] Yoklama "anlik veri yok" kurali eklendi (yaniltici cevap engellendi)
- [x] Halusinasyon kurali guclendirildi: "ASLA soru uydurma, icerik'teki metni oku"
- [x] daily_report + sentiment_tracker scheduler eklendi (bridge lifespan icinde)
- [x] Ders normalizasyonu: 36 AYT + 8 EA + 24 Bio ders etiketi duzeltildi
- [x] Konu normalizasyonu: 41 TYT + 12 Kimya + EA temizligi
- [x] Context kurallari: "goster/evet/2023" fast response'tan cikarildi → Claude context
- [x] Keyword search: 2 asamali (once konu, sonra icerik fallback) + ders filtresi

### Konusma Analizi Bulgulari (Duzeltildi)
- [x] ToolUseBlock sizması — send_exam_image yanlis parametre → prompt kurali
- [x] "Onu goster" → ogrenci profili geliyordu → fast response bypass
- [x] "2023" tek yil → fast response'a dusuyordu → Claude'a yonlendirildi
- [x] Soru 99 halusinasyon ("ova hucreleri surfu") → prompt kurali guclendi
- [x] "Tum ogretmenler yoklama almis" yanlis → "anlik yoklama verisi yok" kurali
- [x] Duygu'ya "Sayin Mudurum" hitabi → isimle hitap

## Tamamlanan Gorevler (23 Nisan 2026 — Oturum 23: Brans Yetki + Tercih Robotu)

### Brans Ogretmeni Yetki Duzeltmesi (Neo karari)
- [x] Brans ogretmeni ARTIK EYOTEK'te ETUT YAZAMAZ — etutleri sadece rehber yazar
- [x] `ogretmen_etut_takvimim` — ogretmen kendi etut takvimini okur + GCal quick-add linkleri (READ-ONLY)
- [x] `ogretmen_etut_onerisi` — brans ogretmeni rehbere tavsiye yazar (DB: teacher_etut_onerileri)
- [x] Rehber `build_rehber_brief()` — bekleyen brans ogretmeni onerilerini listeler (oncelik siralamali)
- [x] `role_access.py`: ogretmen'dan `plani_takvime_ekle`, `etut_takvime_ekle` kaldirildi
- [x] `teacher_etut_onerileri` DB tablosu: durum (bekliyor/incelendi/yazildi/reddedildi), oncelik (dusuk/normal/yuksek/acil)
- [x] Tool schemas: `ogretmen_etut_takvimim` + `ogretmen_etut_onerisi`

### Tercih Robotu Modu (YKS sonrasi asistan, altyapi HAZIR bayrak KAPALI)
- [x] `tercih_robotu.py` (505 satir) — YKS sonrasi ogrenci asistan motoru
- [x] Sezon yonetimi: `TERCIH_DONEMI_BASLANGIC=2026-07-01`, `BITIS=2026-08-31`
- [x] Neo admin komutu: `tercih modu ac` / `tercih modu kapa` / `tercih durum`
- [x] Otomatik aktivasyon: tarih pencere icinde VEYA Neo manual "ac" dediyse
- [x] `sistem_ayar` DB tablosu (TERCIH_DONEMI_ACTIVE=false, Neo YKS sonucu sonrasi acar)
- [x] `tercih_profil` DB tablosu: soz_no, yerlesme_puani, siralama, puan_turu (SAY/EA/SOZ/DIL),
      tercih_sehirler[], tercih_bolumler[], kacinmak_istedigi[], burs_durumu, aile_butce_ust, sehir_kisiti_katalik
- [x] `tercih_listesi` DB tablosu: versiyonlu taslak listeler (liste_json JSONB, durum, rehber_notu)
- [x] 5 Claude tool: tercih_profili_kaydet / _getir / tercih_listesi_uret / bolum_karsilastir / tercih_donemi_durum
- [x] Prompt enjeksiyonu: ogrenci+rehber rolunde tercih modu aktifse system prompt'a TERCIH_ROBOTU_PROMPT eklenir
- [x] Liste algoritmasi: 18-24 satir, 4 bant (garanti/orta/hedef/hayal), YUZDELIK bantlar
   - garanti: %3-%10 daha asagi siralama (kesin girer)
   - orta: ±%3 (yerinde)
   - hedef: %3-%15 daha yukari (zorla)
   - hayal: %15-%30 daha yukari (sans)
   - Min bant genisligi 100 (top 1000 icin yuzde yetersiz kalirsa)
- [x] PostgreSQL `unaccent` extension kuruldu — Turkce karakter toleransli arama
- [x] YOK Atlas verisi: `universite_taban` 35.584 kayit (yil: 2022-2025, SAY 11.081 + EA 11.153 + SOZ 11.054 + DIL 2.296)
- [x] KVKK: ogrenci SADECE kendi tercih profilini gorur, rehber/mudur tumune erisir, ogretmen+veli erisemez
- [x] SQL ACL guard: `TERCIH_PROFIL` ve `TERCIH_LISTESI` hassas tablolar listesine eklendi (ogrenci kendi soz_no)

### Yeni Dosyalar (Oturum 23)

| Dosya | Rol |
|-------|-----|
| `tercih_robotu.py` | YKS sonrasi tercih danismani modu (5 fonksiyon + 2 prompt) |
| `teacher_copilot.py::build_rehber_brief` | Rehber icin bekleyen brans ogretmeni onerileri |

### Yeni DB Tablolari (Oturum 23)

| Tablo | Kayit | Aciklama |
|-------|-------|----------|
| `teacher_etut_onerileri` | 0 | Brans ogretmeni → rehber oneri kuyrugu |
| `tercih_profil` | 0 | Ogrenci YKS tercih profili (soz_no PK) |
| `tercih_listesi` | 0 | Uretilen taslak tercih listeleri (versiyonlu) |
| `sistem_ayar` | 1 | TERCIH_DONEMI_ACTIVE=false |

### Zaman Cizelgesi (YKS 2026)

| Olay | Tarih | Kaldi |
|------|-------|-------|
| TYT | 13 Haziran 2026 | 51 gun |
| AYT | 14 Haziran 2026 | 52 gun |
| OSYM Sonuc | ~3 Temmuz 2026 | 71 gun |
| Tercih Donemi | 1 Tem - 31 Agu 2026 | 69-131 gun |
| Yaz Kampi | 1 Eylul 2026 oncesi | 131 gun |

## Tamamlanan Gorevler (24 Nisan 2026 — Oturum 24+25: VPS Regresyon + Groq Genisleme)

### Oturum 24 — Baglam kaybi fix + Groq observability
- [x] **conversation_memory baglam kaybi fix**: 3h INTERVAL penceresi kaldirildi, LIMIT 6 ile en yeni mesajlar cekilir. Temporal marker eklendi ("AKTIF"/"BUGUN/DUN"/"N gun once"). Canli analiz 17 baglam_kaybi hatasi tespit ettigi icin bu fix kritik.
- [x] **VPS regresyon**: chat_local() Ollama-only idi, Groq 70B hic calismiyordu. is_local_available artik Groq'u da sayiyor, chat_local Groq-first + Ollama fallback.
- [x] **Groq observability fix**: routing_stats/usage_log'a response_source='groq' DINAMIK yaziliyor (onceden "ollama" hardcoded).
- [x] **fermat_start.py gunluk ozette** groq sayaci eklendi.
- [x] **conversation_quality_analyzer.py** (YENI): Groq 70B ile son 72h konusma kalite denetimi. ~$0.10/50 konusma. Ilk rapor: ort 5.84/10, 33 frustration, 42 bot hatasi (17 baglam_kaybi, 17 yanlis_data, 4 halusinasyon), 25 eksik pattern.
- [x] **RAG content expansion** --groq flag (rag_content_builder): Llama 3.3 70B ile icerik uretimi ~$0.003/konu (Claude'un 1/7'si). 15 yeni konu eklendi.
- [x] **VPS'e Ollama + nomic-embed-text kuruldu** — RAG embedding backend; Python `ollama` paketi venv'e eklendi.

### Oturum 25 — Groq tool-calling + token pass
- [x] **ENABLE_GROQ_TOOLS env flag** (default false, production emniyeti)
- [x] **SAFE_GROQ_TOOLS allowlist**: search_curriculum, get_class_plan, list_exam_questions, get_daily_etut (sadece read-only, dusuk risk)
- [x] **LLMRouter.chat_groq_with_tools()** (YENI): 1-2 round tool-calling. HERHANGI bir hata (invalid JSON, whitelist disi tool, executor fail, API hatasi) → None doner, caller Claude'a sessizce fallback eder.
- [x] **test_groq_tools.py** smoke test: 3/3 gecti VPS'te (search_curriculum dispatch + whitelist koruma + no-tool text).
- [x] **Token sayimi (tiktoken ile)**: SYSTEM_PROMPT 27,649 tok (hedef 18k, +9.6k fazla).
- [x] **Guvenli annotation cut**: dev annotation (dated parenthesis, Oturum refs, 22.1n kodlari) temizlendi → **168 token tasarruf**, davranis degisikligi YOK. Buyuk sikistirma A/B test oturumuna ertelendi.
- [x] **Safety net**: git tag `oturum-24-stable` + `.baseline_o24` local dosya yedekleri.

### Groq 70B Aktivasyon Recetesi (bir sonraki oturum icin)

`chat_groq_with_tools` hazir ama `chat()` routing'ine wire edilmedi. Aktivasyon icin:
1. VPS .env: `ENABLE_GROQ_TOOLS=true` ekle
2. fermat_core_agent.py Claude tool-calling loop basinda kontrol:
   ```python
   if (ENABLE_GROQ_TOOLS and role == "ogrenci"
       and all(t['name'] in SAFE_GROQ_TOOLS for t in tools_to_use)):
       result = await self.router.chat_groq_with_tools(
           self.history, system, tools_to_use, self._dispatch_tool)
       if result and result.get('text'):
           # use Groq result, log as response_source='groq'
           ...
       # else fall through to Claude (current behavior)
   ```
3. `_dispatch_tool` helper yaz (tool_name + args → str)
4. 1-2 ogrenci ile canli test, sonuclara gore tam aktive et

### Yeni Routing Hedefi (VPS + Groq sonrasi)

| Kaynak | Eski Hedef | Yeni Hedef | Aciklama |
|--------|-----------|-----------|----------|
| Fast Response | %50 | %45 | Selamlama, veri, guvenlik (degismedi) |
| Groq 70B | %0 | %30 | Kavramsal + basit sohbet + (aktive edilirse) safe tool |
| Ollama | %20 | %0 | VPS'te yok (Groq onu degistirdi) |
| Claude API | %30 | %25 | Hassas, tool-calling (write), analiz, duygu/kriz |

### Yeni Dosyalar (Oturum 24+25)

| Dosya | Rol |
|-------|-----|
| `conversation_quality_analyzer.py` | Son N saat konusma kalite denetimi (Groq 70B, ~$0.10/50 konusma) |
| `test_groq_tools.py` | Groq tool-calling smoke test (3 senaryo) |
| `system_prompts.py.baseline_o24` | Token kesim oncesi yedek (rollback icin) |
| `llm_router.py.baseline_o24` | Groq degisiklikleri oncesi yedek |
| `fermat_core_agent.py.baseline_o24` | Yedek |

### Tamamlanmayan (Oncelik + Sonraki oturum)

- [ ] **Token optimization tam pass**: 27k → 18k. Gerektirir: KURALLAR (3795 tok) ve KESIN YASAKLAR arasi ASLA/YASAK consolidation, TUTARSIZLIK TESPIT sadelestirme, QUERY_ANALYTICS SQL ornekleri compact. A/B test zorunlu.
- [ ] **Groq tool-calling activation**: yukaridaki recete + canli test
- [ ] **LGS topic_tracker**: student_exam_analysis tablosunda LGS kaydi yok. Eyotek LGS konu bazli scraper yazilmali (yeni is).
- [ ] **17 yanlis_data + 4 halusinasyon** (kalite raporundan): bot'un sayi/veri uydurma riskine karsi prompt guardrails guclendirilmeli.

## Tamamlanan Gorevler (15 Nisan 2026 — Oturum 17: UX + Hiz + Registry)

### UX Devrim
- [x] `conversation_flow.py` — uzun-intent tespit (12 kategori) + 68 filler varyasyon
- [x] Per-phone async lock + queue (concurrent mesaj cakismasi yok)
- [x] Sirayla isleme (merge yerine) — her mesaj kendi cevabi
- [x] Reaction (👍❤️) filter — bot sessiz
- [x] Queue bilgi mesajlari (7 varyasyon) + progress (10 varyasyon)
- [x] Watchdog 3sn — bypass bug fix (satir 1978 agent.run early return kaldirildi)

### Hiz + Guvenilirlik
- [x] Tool_call paralel (`asyncio.gather`) — Claude path %40 hizlandi (29s→17s)
- [x] DB pool altyapi (min=2, max=10) + db_fetch/fetchrow/fetchval helperleri
- [x] Ollama warmup boot'ta (cold start yok)
- [x] Anthropic SDK sync→`asyncio.to_thread` (event loop bloke etmiyor — watchdog calisir)

### AYT Veri Pipeline
- [x] YKS sekme bug 3 katmanli fix (LI>A tikla, aktif tab pane, ikon-bazli katilim)
- [x] `get_ayt_analysis(soz_no)` ozel Claude tool — TOPLAM→sinav basi ortalama
- [x] student_exam_analysis AYT kolonlari (ham_puan_ayt, yerlesme_puani_ayt, ders_netleri_ayt...)
- [x] scrape_exam_analysis.py --ayt flag + v3 scrape → 30 ogrenci AYT DB'de
- [x] Taha PDF karsi test → %100 tutarlilik (Ham 402.7, Yerlesme 459.7)

### Fast Response Genisleme
- [x] Konu→ders mapping (manyetizma→fizik, turev→mat, hucre→bio, osmanli→tarih)
- [x] Admin tek-kelime (neo/admin/yardim) fast
- [x] Hack injection 5 deneme → 1 saat auto blok (in-memory)
- [x] Selam+soru ayrimi ("Selam, bugun hoca kim" → Claude, saf "selam" fast)
- [x] claude_kisisel_hedef handler ("netlerimle hangi universite" → Claude analiz)
- [x] Frustration generic ozur kaldirildi → her "yanlis" Claude eskalasyon

### Ollama Rol Guclendirme
- [x] Kavramsal sorular → Ollama (halusinasyon-safe, kisisel veri korumali)
- [x] _PERSONAL_KEYWORDS (benim/netim/zayifim/Taha/Ecrin) → her zaman Claude
- [x] Ollama system prompt: "Kavramsal asistan — kisisel veri YASAK"
- [x] _clean_ollama_format (markdown→WA, emoji filter, kod blok temizle)

### Pre-Built Registry (15 Nisan 17:30)
- [x] `student_query_registry.py` — 26 senaryo (fast 18, Claude 7, Ollama 1)
- [x] Son 30 gun real konusmadan %80 kapsam
- [x] Claude prompt'a OGRENCI SENARYO HAZIRLIKLARI enjekte
- [x] `KALDIGIM.md` — session continuity hafiza dosyasi

### Bug Fixes (konusma analizi sonrasi)
- [x] Selam+soru mesajinda context kaybi — pattern uzunluk kontrolu
- [x] SOHBET_OGRENCI list .replace bug
- [x] AYT deneme fonksiyonuna Eyotek resmi puan ustte
- [x] Bridge --reload kapatildi (zombi PID sorunu yok)
- [x] v14→v21 bridge restart (her biri fix'ler)

## Yeni Dosyalar (Oturum 17)

| Dosya | Rol |
|-------|-----|
| `conversation_flow.py` | Filler + watchdog + post-followup + queue |
| `student_query_registry.py` | 26 senaryo referans belgesi (%80 kapsam) |
| `KALDIGIM.md` | Session continuity hafiza |

## Bekleyen Gorevler (Oncelik Sirasıyla)

### 🔴 ACIL (1-2 hafta)
1. **Alarm sistemi aktif etme** — Neo onayladiktan sonra ALERTS_ACTIVE=True, cron kurulumu
2. **Session keeper otonom calisma** — session_keeper.py otomatik baslatma, drop recovery
3. **write_etut ogrenci arama fix** — BtnSearchStudent PostBack new_page'de calismıyor
4. **PDF kaynak import pipeline** — PDF → metin cikarma → chunk → embedding → pgvector (NotebookLM tarzi)
5. **MEB OGM Materyal scraping** — https://ogmmateryal.eba.gov.tr (Angular SPA, Playwright ile)
   - MEB'in ana bilgi kaynagi — ders kitaplari, test sorulari, konu anlatim materyalleri
   - Tum sinif seviyeleri ve dersler mevcut
   - Angular SPA — Playwright CDP ile icerik cekilecek, PDF/icerik indirip RAG'a import
   - Benzer kaynaklar: EBA icerik, MEB mufredat kazanimlari
   - KESFEDILEN URL YAPISI:
     /mebi-konu-ozetleri → TYT (8 kitap ID:176268-176275) + AYT (ID:176283+) konu ozetleri
     /soru-bankasi → Ders bazli soru bankasi (Sinif+Ders filtresi)
     /icerik-goster/{id} → Online goruntule
     /mebi-ozet-indir?id={id} → PDF indir
     /icerik-indir/{id} → ZIP indir
   - YKS Hazirlik alt menuleri: MEBi Tarama Testi, Cikmis Soru, 3 Adim Soru Bankasi,
     3 Adim Deneme, Dort Dortluk Pekistirme, YKS Kampi, Konu Anlatim Video, Cikmis Cozum
   - ONCELIK: Konu Ozetleri PDF → RAG import (en hizli deger)

### 🟡 ORTA VADE (2-4 hafta)
4b. **Iletisim Telafi Mekanizmasi** — Zayif cevap sonrasi otomatik duzeltme mesaji
   - Tetik: ogrenci "anlamiyorsun/yanlis/tekrar" dediginde frustration_log'a kaydet
   - Guncelleme sonrasi: sorun duzeltildiyse telafi kuyruğuna ekle
   - Kontroller: 08-20 arasi, son etkileşimden 15dk-30dk sonra, 24 saati gecmemis
   - Format: "Dusundum de, daha once sordugun [konu] hakkinda seni daha iyi anlayabilirdim..."
   - ONKOSUL: Alarm sistemi canli + test edilmis olmali (ALERTS_ACTIVE=True)
   - RISK: Yanlis tetiklenme, gece mesaj, sacma icerik — cok dikkatli test edilmeli
5. ~~Vision PDF Import — sözel kitaplar~~ — **NEO KARARI 23 NİSAN: İPTAL** (kurum SAY+EA odaklı, sözel öğrenci yok; gerekli içerik zaten RAG'da var — 390 OGM Vision + 4056 PDF)
6. **PDF pedagojik icerik** — Egitim metodolojisi, kocluk teknikleri → bot davranis rehberi
7. **Puan tahmin motoru** — mevcut trendden YKS puan tahmini, hedef bolum icin gereken net
8. **Akilli etut planlama** — zayif konu + musait ogretmen + bos derslik → otomatik oneri
9. **RAG genisleme** — AYT konulari, Fen/Sosyal, video linkleri
10. ~~Sesli mesaj (Whisper)~~ — **ZATEN AKTİF** (OPENAI_API_KEY set, `_transcribe_audio` Whisper-1 ile WP ses → metin çalışıyor)

### 🟢 UZUN VADE (1-3 ay)
11. **Ogrenci kisisel AI kocu** — gunluk check-in, pomodoro, Feynman teknigi
12. **Veli portali** — otomatik haftalik rapor, randevu sistemi
13. **Ogretmen dashboard (web)** — sinif bazli performans goruntulemesi
14. **Mezun takip sistemi** — yerlesme sonuclari, referans, sosyal medya icerik
15. **Konu zorluk haritasi** — kurum geneli hata analizi → ogretmen toplantisina girdi
16. **Web Tabanli Chat Arayuzu** — WhatsApp'in eksikleri icin alternatif (Neo notu, 14 Nisan 2026):
    - "Yaziyor..." gostergesi (typing indicator) — gercek dialog hissi
    - Streaming response (Claude'un cevabi parca parca akar, beklenmez)
    - Markdown render (kod, formul, tablo dogru gosterilir)
    - Gecmis search (eski konusmalari ara)
    - Faz 1: FastAPI + WebSocket + minimal React/HTMX (kurum ici)
    - Faz 2: Tek tikla mobile responsive (telefondan da)
    - Faz 3: Fermat brand uyumlu, ogrenci/ogretmen rolune gore farkli paneller
    - Avantaj: WhatsApp tarafini koruyup web'i UPGRADED kanal yapariz
    - WhatsApp = casual / web = derinlemesine analiz

### 🔧 BILINEN ZAYIF YONLER
- **Eyotek session drop KRITIK SORUN**: ASP.NET session ~20-30dk'da timeout yapiyor.
  keep_session_warm() HTTP GET yeterli degil. Cozum onerileri:
  a) Playwright CDP ile 3dk'da bir gercek sayfa navigate (Chrome tab uzerinden)
  b) ASP.NET session cookie'sini analiz et — hangi cookie expire oluyor bul
  c) Chrome extension ile auto-refresh (en basit)
  d) Eyotek API endpoint varsa session renew istegi gonder
  Mevcut workaround: session_keeper.py + admin "eyotek tamam" komutu
- Session keeper fermat_start.py ile baslatilmali — bagimsiz calismiyor
- write_etut ogrenci arama PostBack bug'i — etut yazma %80 calisiyor, ogrenci secimi sorunlu
- Alarm sistemi hazir ama KAPALI (ALERTS_ACTIVE=False) — test edilmedi canli ortamda
- PDF import pipeline henuz yok — RAG sadece Claude-uretimi icerik ile dolu (36 konu)
- LGS ogrencileri icin topic_tracker verisi yok (sadece TYT/AYT konulari var)
- Bazi ogrencilerin sinif bilgisi yanlis formatta ("[10] 10 SAY A" gibi prefix'li)
- Ollama tek kelimelik mesajlarda halusilasyon riski (context eksikligi)

## Bilinen Sorunlar ve Çözümleri

| Sorun | Çözüm |
|-------|-------|
| Sonsuz sayfa döngüsü | `effective_total = total_pages` (max() kullanma) |
| ARA modal açılmıyor | `#btnCloseSearchModal` selector, `walked_up_from_closeBtn` |
| CDP bağlantı hatası | Chrome `--remote-debugging-port=9222` ile aç |
| `class_name=""` crash | eyotek_wrapper'da boşsa atla (fix uygulandı) |
| Turkish İ search | `_TR_TO_UPPER` maketrans kullan |
| Staff schema `ik_no` vs `eyotek_id` | `eyotek_id` standart (fix uygulandı) |
| .env yüklenmeme sorunu | `load_dotenv(override=True)` kullan |
| Windows emoji encoding | `print()` içinde emoji yerine `[TAG]` kullan |
| CDP tab çakışması | `new_page()` kullan, `browser.close()` yapma |
| Session süresi dolma | `_goto()` login algılar, Chrome'dan cookie yeniler |
| counsellor_note St_Id | `get_student_profile` grid'de öğrenci bulamıyor — ARA filtre iyileştirmesi gerekli |

## Çalıştırma Komutları

```powershell
# Ortamı aktifleştir
cd C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent
.venv\Scripts\activate

# Chrome CDP modunda başlat (ayrı terminal)
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug"

# Veri sync
python eyotek_agent.py
python eyotek_agent.py students
python eyotek_agent.py attendance

# Agent test
python fermat_core_agent.py "bugün kimler gelmedi"
python fermat_core_agent.py "Ali Küçükuysal için yarın 12:00'da fizik etüt yaz"

# Bridge başlat (PORT 8001 — ChromaDB 8000 kullanıyor)
uvicorn whatsapp_bridge:app --host 0.0.0.0 --port 8001 --reload

# Sınav analizi toplu çekimi
python scrape_exam_analysis.py         # Tüm öğrenciler
python scrape_exam_missing.py          # Sadece eksik öğrenciler

# Sabah briefing
python daily_briefing.py               # Konsola yaz
python daily_briefing.py --send        # WhatsApp'a gönder
```
