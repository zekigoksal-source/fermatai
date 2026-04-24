# FermatAI — Çalıştırma Sırası ve Mimari Rehberi

**Güncelleme: 06 Nisan 2026 — v4.0 Tam Yığın**

---

## Genel Mimari

```
WhatsApp Sesli/Yazılı Komut
         │
         ▼
  whatsapp_bridge.py          ← FastAPI webhook (Meta API)
         │  ses → Whisper/Anthropic ASR
         ▼
  intent_parser.py            ← Kural + LLM (Haiku) niyet analizi
         │
         ▼
  fermat_core_agent.py        ← Claude tool-calling + pedagojik muhakeme
         │          │
         │          └── PostgreSQL (asyncpg) — analitik sorgu
         ▼
  eyotek_wrapper.py           ← Playwright CDP → Eyotek LMS yazma
         │
         ▼
  WhatsApp yanıt → öğrenciye/veliye bildirim
```

---

## Dosya Envanteri

| Dosya | Katman | Açıklama |
|-------|--------|----------|
| `explore_student_profile.py` | Keşif | v3.3 — Eyotek profil haritacısı |
| `eyotek_agent.py` | Veri | Toplu scraping → PostgreSQL |
| `eyotek_wrapper.py` | Eylem | LMS okuma + yazma (Playwright) |
| `fermat_core_agent.py` | Beyin | Claude tool-calling, ACL gate, pedagojik karar |
| `intent_parser.py` | Anlama | WhatsApp komutu → IntentResult + Whisper ASR |
| `whatsapp_bridge.py` | Kapı | Meta webhook, intent followup, oturum yönetimi |
| `db_schema.sql` | Şema | Ana veri tabloları (students, attendance, exams…) |
| `acl_schema.sql` | Yetki | PostgreSQL rol/izin matrisi + audit log |
| `profile_map.json` | Harita | Eyotek form/input/URL yapısı (keşif çıktısı) |
| `site_map.json` | Harita | 297 sayfa URL kataloğu |
| `.env.example` | Yapılandırma | Tüm ortam değişkenleri şablonu |
| `requirements.txt` | Bağımlılık | Python paket listesi |

---

## AŞAMA 0 — İlk Kurulum (Bir Kez)

### 0a. Python ortamı

```powershell
cd C:\Users\zekig\OneDrive\Desktop\FermatAI\eyotek_agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 0b. Ortam değişkenleri

```powershell
copy .env.example .env
# .env dosyasını aç, değerleri doldur:
#   DATABASE_URL, ANTHROPIC_API_KEY, WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, ...
```

### 0c. Veritabanı şemasını oluştur

```powershell
# PostgreSQL kurulu ve DATABASE_URL .env'de ayarlı olmalı
# Önce ana veri tabloları (students, attendance, exams, staff, ...)
psql %DATABASE_URL% -f db_schema.sql

# Ardından yetki matrisi (acl_users, acl_permissions, eyotek_action_log, ...)
psql %DATABASE_URL% -f acl_schema.sql
```

### 0d. Admin kullanıcı ekle

```sql
-- psql içinde:
INSERT INTO acl_users (phone, full_name, role, is_active)
VALUES ('+905XXXXXXXXX', 'Zeki Göksal', 'admin', TRUE)
ON CONFLICT (phone) DO NOTHING;
```

### 0e. Chrome'u CDP modunda başlat

```powershell
# Yeni terminal — Chrome'u uzaktan debuggable aç
"C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="C:\ChromeDebug"
# Chrome'da fermat.eyotek.com'a giriş yap
```

---

## AŞAMA 1 — Eyotek Harita Güncellemesi (Gerektiğinde)

Eyotek form yapısı değişirse veya ilk kurulumda `profile_map.json` yoksa çalıştır.

```powershell
.venv\Scripts\activate
python explore_student_profile.py
```

**Beklenen çıktı:** `profile_map.json` — 20 anahtar, ~511K karakter
**Kritik kontroller:**
- `ara_modal_html_debug.selector` → `walked_up_from_closeBtn`
- `ara_modal.inputs` → 72 input
- `context_menu.postback_map` → 36 PostBack
- `counsellor_note_form.visible_textareas[0].id` → textarea ID (v3.3 yeni)

---

## AŞAMA 2 — Toplu Veri Senkronizasyonu

PostgreSQL'i Eyotek verisiyle doldur. İlk çalıştırmada tüm modüller, sonrasında planlanmış zamanlayıcıyla.

```powershell
# Tüm modüller (öğrenci + yoklama + sınav + ödev)
python eyotek_agent.py

# Seçili modüller
python eyotek_agent.py students
python eyotek_agent.py attendance
python eyotek_agent.py students attendance
```

**Beklenen:** Her öğrenci için UPSERT, yoklama için snapshot insert, sayfa başına ~10 saniye.

---

## AŞAMA 3 — WhatsApp Bridge'i Başlat

```powershell
.venv\Scripts\activate
uvicorn whatsapp_bridge:app --host 0.0.0.0 --port 8000 --reload
```

Veya `.env`'de `BRIDGE_PORT` ve `DEV_MODE` ayarlıysa:

```powershell
python whatsapp_bridge.py
```

**Sağlık kontrolü:**
```
GET http://localhost:8000/health
→ {"status":"ok","active_sessions":0,"db_configured":true,"wa_configured":true}
```

---

## AŞAMA 4 — Meta Webhook Kaydı

1. [Meta Developer Portal](https://developers.facebook.com) → WhatsApp → Configuration
2. **Callback URL**: `https://senin-domain.com/webhook`
   (ngrok ile test için: `ngrok http 8000` → https URL'i al)
3. **Verify Token**: `.env`'deki `WA_VERIFY_TOKEN` değeri
4. **Subscribe**: `messages` alanını işaretle

---

## TEST — CLI Modu

Bridge'i başlatmadan doğrudan agent testi:

```powershell
# Tek mesaj testi
python whatsapp_bridge.py test "Ahmet'i raporla"
python whatsapp_bridge.py test "11 SAY A'ya fizik etüt yaz"
python whatsapp_bridge.py test "Bugün kimler gelmedi"
```

n8n veya HTTP istemcisiyle test:

```powershell
curl -X POST http://localhost:8000/agent `
  -H "Content-Type: application/json" `
  -d "{\"phone\":\"+905000000000\",\"message\":\"Ahmet'e rapor çek\"}"
```

---

## ACL — Rol Matrisi Özeti

| Rol | get_student_analytics | execute_eyotek_action | send_sms | Kapsam |
|-----|-----------------------|-----------------------|----------|--------|
| admin | ✅ | ✅ | ✅ | Tüm okul |
| mudur | ✅ | ✅ | ✅ | Tüm okul |
| ogretmen | ✅ | ✅ | ❌ | Kendi sınıfları |
| rehber | ✅ | ✅ (sadece not) | ❌ | Tüm okul |
| veli | ✅ | ❌ | ❌ | Sadece kendi çocuğu |
| ogrenci | ✅ | ❌ | ❌ | Sadece kendisi |
| guest | ❌ | ❌ | ❌ | Yok (onay bekliyor) |

---

## Tipik Akış — "Ahmet'e rapor çek, zayıfsa Fizik'e etüt yaz"

1. **WhatsApp** → `whatsapp_bridge.py` POST `/webhook` alır
2. **intent_parser** → `STUDENT_REPORT` + `{student_name: "Ahmet"}` çıkarır
3. **ACL** → telefon numarasına göre rol doğrular
4. **fermat_core_agent** → `get_student_analytics("Ahmet")` tool çağrısı
5. **PostgreSQL** → Ahmet'in devamsızlık, net ortalaması, borç durumu döner
6. **Claude** → pedagojik analiz: `risk_level = "yüksek"` → Fizik etüt kararı
7. **fermat_core_agent** → `execute_eyotek_action(action="write_etut", ...)` çağrısı
8. **eyotek_wrapper** → Playwright CDP ile Eyotek'e etüt yazar
9. **whatsapp_bridge** → öğretmene/veliye WhatsApp yanıtı gönderir

---

## Güvenlik Kuralları

- `WA_APP_SECRET` set edilmişse her POST'ta `X-Hub-Signature-256` doğrulanır
- ACL'siz telefon numaraları `guest` rolü alır → tüm tool'lar engellenir
- `execute_eyotek_action` loglanır: `eyotek_action_log` tablosu
- `dry_run=True` ile SMS/etüt önizleme — gerçek yazma yapılmaz

---

## Sorun Giderme

| Sorun | Neden | Çözüm |
|-------|-------|-------|
| `profile_map.json` JSONDecodeError | Null byte sonu (`\x00`) | `raw.rstrip(b'\x00')` sonra yeniden yaz |
| ARA modal açılmıyor | `.modal-content` yerine özel popup | `#btnCloseSearchModal` selector kullan |
| CircularImport eyotek_wrapper | `from eyotek_agent import ...` | `_build_header_map_local()` lokal impl. var |
| CDP bağlantı hatası | Chrome kapalı veya port farklı | `CDP_PORT` kontrol et, Chrome'u yeniden aç |
| `anthropic` paketi yok | pip eksik | `pip install anthropic>=0.25.0` |
| WhatsApp 403 imza hatası | `WA_APP_SECRET` yanlış | `.env`'deki değeri kontrol et |
| Session süresi dolmuş | Eyotek cookie expired | Chrome'da yeniden giriş → yeni session |

---

## Tamamlananlar (07 Nisan 2026 — Oturum 3)

### Güvenlik & Altyapı
- [x] Konuşma geçmişi DB kaydı — `agent_conversations` tablosuna otomatik INSERT
- [x] `/agent` endpoint API key güvenliği — `AGENT_API_KEY` ile Bearer token
- [x] Rate limiting — per-phone max 10 mesaj/dakika
- [x] `load_dotenv(override=True)` — .env yükleme sorunu düzeltildi

### Eyotek Wrapper İyileştirmeleri
- [x] CDP fix: `new_page()` ile yeni sayfa açma — kullanıcı tab'larına dokunmaz
- [x] `browser.close()` kaldırıldı — Chrome kapanması engellendi
- [x] Session auto-refresh: login algılama + Chrome'dan taze cookie alma
- [x] `write_counsellor_note` dry_run parametresi eklendi
- [x] Hata screenshot yakalama — `logs/` klasörüne PNG

### Veritabanı
- [x] `etut_records` tablosu oluşturuldu (etüt kayıtları)
- [x] `homework` tablosu oluşturuldu (ödev kayıtları)
- [x] Staff tablosu schema güncellendi (eyotek_id PK)
- [x] `CALISTIR.bat` çalıştırıldı — 2 çöp kayıt silindi, 18 personel import edildi

### Yeni Dosyalar
- [x] `daily_briefing.py` — sabah özeti (devamsız, riskli, agent kullanımı)
- [x] `.claude/launch.json` — dev server konfigürasyonu

### Testler
- [x] 18/18 sistem testi geçti
- [x] write_etut canlı dry-run başarılı (öğrenci+öğretmen bulma, parametre çıkarma)
- [x] write_counsellor_note testi — session refresh çalıştı, St_Id sorunu tespit edildi
- [x] WhatsApp bridge CLI testi başarılı

---

## Planlı Görevler (Sonraki Adımlar)

- [ ] `write_etut` v2.0 **canlı testi** — `dry_run=False, confirmed=True` ile ilk gerçek etüt yazma
  - Test komutu: `python whatsapp_bridge.py test "EZGİ için yarın 12:00'da Matematik etüdü yaz"`
  - Öncesinde: Chrome CDP açık + Eyotek oturumu aktif + PostgreSQL bağlantısı sağlıklı
- [ ] `write_counsellor_note` canlı testi — `btnAddNote` tıklaması + textarea ID doğrulama
- [ ] Mass sync PostgreSQL canlı testi — gerçek veri doldur
- [ ] ngrok ile Meta webhook doğrulama testi
- [ ] Ses mesajı (WhatsApp voice note) uçtan uca testi
- [ ] Zamanlanmış görev: gece `eyotek_agent.py attendance` cron

## Tamamlananlar (06 Nisan 2026 — Oturum 2)

### Öğrenci & Personel DB İmport
- [x] `students_export.json` — Chrome MCP ile 125 öğrenci scrape edildi (soz_no 137–314)
- [x] `import_students.py` — 125 öğrenci PostgreSQL'e yüklendi, ALİ KÜÇÜKUYSAL (soz_no 167) doğrulandı
- [x] `staff_export.json` — Chrome MCP ile 18 personel scrape edildi (ZEKİ GÖKSAL eyotek_id 1035)
- [x] `import_staff.py` — 18 personel için hazır, çalıştırılmayı bekliyor
- [x] `cleanup_db.py` — eski bozuk sync kayıtlarını (eyotek_id < 100) temizler
- [x] `add_admin.py` — ACL tablosuna Zeki Göksal'i admin ekler (çalıştırılmayı bekliyor)

### Pagination Fix (eyotek_agent.py)
- [x] Sonsuz döngü düzeltildi — `effective_total = max(total_pages, 9999)` → `total_pages` kullan
- [x] İçerik değişmediğinde `break` eklendi (aynı sayfa tekrar gelince dur)
- [x] Staff modülü düzeltildi: URL `working-hours-edit` → `staff`, `needs_ara=True`, schema yenilendi

### fermat_core_agent.py İyileştirmeleri
- [x] `datetime` import eklendi
- [x] Dinamik tarih context: agent "yarın" yazınca doğru tarihi biliyor
- [x] `tool_search_students` → `soz_no` + `sube` da dönüyor, soz_no eşleşmesi eklendi
- [x] `tool_check_teacher_availability` → yeni staff schema (`eyotek_id`, `gorev`)
- [x] Agent prompt: `class_name` null ise `sube` fallback kuralı eklendi

### eyotek_wrapper.py
- [x] `write_etut` ADIM 5: `class_name=""` ise form crash etmiyor, öğrenci adıyla devam eder

### Zamanlanmış Görev
- [x] `fermatai-daily-sync` — Her hafta içi 08:01'de Eyotek devamsızlık otomatik çekiliyor
  - Çıktı: `FermatAI/devamsizlik_YYYY-MM-DD.json`
  - Yönetim: Claude sidebar → Scheduled bölümü

---

## Tamamlananlar (06 Nisan 2026 — Oturum 1)

- [x] Eyotek etüt girişi formu tam haritalandı (21 input/select/button ID)
- [x] `write_etut()` v2.0 yeniden yazıldı — takvim grid tıklama + modal doldurma
- [x] `write_etut_for_class()` v2.0 yeniden yazıldı — `write_etut(select_all_in_class=True)` delege
- [x] `intent_parser.py` güncellendi — `target_date` (DD.MM.YYYY) ve `ders_no` entity çıkarımı
  - `12:00da`, `14:00de` gibi Türkçe ek ekleri için `\b` → `(?!\d)` lookahead düzeltmesi
  - `bugün` / `yarın` → otomatik tarih dönüşümü
  - saat → ders_no tam ve ±10 dk yakın eşleme
- [x] Tüm 5 ana Python dosyası syntax hatası yok (`py_compile` OK)

---

## Referans: Keşfedilen Eyotek Form ID'leri

### Etüt Girişi v2.0 (`individual-lesson-input`) — **TAM HARİTALANDI** ✅

**Güncelleme: 06 Nisan 2026 — Chrome DOM inspect + JavaScript reverse ile keşfedildi**

#### Takvim Grid
| Yapı | Açıklama |
|------|----------|
| `table.ozel` | Ana takvim tablosu |
| Satır hücre[0] | Tarih: "DD.MM.YYYY\nGünAdı" formatında |
| Sütunlar 1-15 | Ders No (zaman dilimleri 09:00 → 20:35) |
| `GrdIndividualLessons_bi{N}_1_{row}` | "+" buton ID deseni |
| `btn.click()` | Tıklama → PostBack → modal açılır |

#### Modal — Normal Mod Öğrenci Seçimi
| ID | Tür | Açıklama |
|----|-----|----------|
| `TxtAddStudentNameNormal` | input[text] | Öğrenci Adı arama |
| `DdlAddClassesNormal` | select | Sınıf ("[id] ClassName" format) |
| `BtnSearchStudent` | PostBack | LİSTELE — öğrenci listesini doldurur |
| `LstAddStudentsNormal` | select[multiple] | Öğrenci listesi (AJAX) |
| `BtnLstAddSelectAllStudents` | PostBack | Tümünü Seç / seçilenleri aktar |
| `BtnGetTheBelowLineList` | PostBack | Çizgi Altı Öğrencilerini Ekle |

#### Modal — Normal Mod Form Alanları
| ID | Etiket | Değerler |
|----|--------|----------|
| `DdlAddIndividualLessonTypeNormal` | Etüt Türü | 1=Etüt, 2=Ek Ders, 3=Özel Ders, 4=Seminer, 5=Sınıf Etüdü |
| `DdlAddLevelNormal` | **Devre** | 1.Snf, 2.Snf … 9.Snf-Hzr (23 seçenek) |
| `DdlAddDurationNormal` | Etüt Süre | 35 (35 dakika) |
| `DdlAddRepeatNormal` | Haftalık Tekrar | 1-10 |
| `TxtAddRemoteLinkNormal` | Uzaktan Eğitim | URL (opsiyonel) |
| `DdlAddLessonNormal` | Ders | 154 seçenek |
| `DdlAddSubjectNormal` | Konu | AJAX (ders seçince dolar) |
| `DdlAddClassroomWatchPlaceNormal` | Derslik | D-2(2), D-3(3), D-4(4), D-5(5), D-6(6) |
| `DdlTeachers` | Öğretmen | 18 seçenek |
| `BtnAddIndividualLessonSaveNormal` | **KAYDET** ✅ | PostBack — gerçek yazma + bildirim! |

#### Çakışma Diyaloğu
| ID | Açıklama |
|----|----------|
| `BtnConflictIndividualLessonSaveNormal` | Tümünü Kaydet (çakışmalara rağmen) |
| `BtnConflictIndividualLessonSaveNormalOnlySaveOthers` | Çakışanları Çıkar Gerisini Kaydet |

#### Ders No → Zaman Dilimi
| Ders No | Hafta İçi |
|---------|-----------|
| 1 | 09:00-09:35 | 2 | 09:45-10:20 | 3 | 10:30-11:05 | 4 | 11:15-11:50 |
| 5 | 12:00-12:35 | 6 | 12:45-13:20 | 7 | 14:00-14:35 | 8 | 14:45-15:20 |
| 9 | 15:30-16:05 | 10 | 16:15-16:50 | 11 | 17:00-17:35 | 12 | 17:45-18:20 |
| 13 | 18:30-19:05 | 14 | 19:15-19:50 | 15 | 20:00-20:35 |

### Rehberlik Notu (`student-counsellor-note`)

| ID | Açıklama |
|----|----------|
| `btnAddNote` | EKLE butonu |
| `cmbNotTuru` | Tür: O(Kanaat) / E(Olay) / P(Telefon) / F(Yüz Yüze) |
| `cmbGorusmeTuru` | STU / PAR / MOT / FAT / SIB |
| `cmbGorunsun` | S(Öğrenci) / P(Veli) / PS(Her İkisi) |

### SMS (`communication-sms-special-text`)

| ID | Açıklama |
|----|----------|
| `lstDevre` | Devre (Tüm Devam Eden…) |
| `cmbProgram` | Program (Tüm Programlar…) |
| `btnGetNotify` | DEVAM ET — öğrenci listesini yükler |

### ARA Modal

| ID | Tip | Açıklama |
|----|-----|----------|
| `cmbSezonlar` | Select2 | Sezon (2025.26…) |
| `cmbSubeler` | Select2 | Şube |
| `cmbSiniflar` | Select2 | Sınıf |
| `txtAd` | text | Ad |
| `txtSoyad` | text | Soyad |
| `txtOgNo` | text | Öğrenci No |
| `btnSearch` | button | ARA |
| `btnCloseSearchModal` | button | Kapat |
