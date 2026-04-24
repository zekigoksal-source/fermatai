# 🔑 API Key Setup — Neo için Talimatlar (23 Nisan)

Bu dokümanda her API için **5 dakika** adımları + **.env** nereye koyulacak.
Kod hazır — key eklediğinde sistem otomatik aktif olur, bridge restart bile gerekmez (lazy init).

---

## 1. 🎥 YouTube Data API v3 (Ücretsiz — 10K istek/gün)

### Adımlar (5 dakika)

1. **Google Cloud Console'a gir**: https://console.cloud.google.com
2. **Proje oluştur** (veya mevcut seç): sağ üstte proje seçici → "Yeni Proje" → "FermatAI"
3. **API'yi etkinleştir**:
   - Sol menü → **"API'ler ve Hizmetler" → "Kütüphane"**
   - Ara: `YouTube Data API v3`
   - Tıkla → **"ETKİNLEŞTİR"**
4. **Key oluştur**:
   - Sol menü → **"API'ler ve Hizmetler" → "Kimlik Bilgileri"**
   - Üstte **"KIMLIK BİLGİLERİ OLUŞTUR" → "API Anahtarı"**
   - Key kopyala: `AIzaSyA...` formatında
5. **Güvenlik** (opsiyonel ama önerilir):
   - Key'i "düzenle" → "API kısıtlamaları" → **"Anahtarı kısıtla"** → Sadece `YouTube Data API v3` seç

### .env'e ekle

```bash
# Fermat eyotek_agent/.env
YOUTUBE_API_KEY=AIzaSyA...senin_keyinler...
```

### Test

```bash
cd eyotek_agent
.venv/Scripts/python.exe external_apis.py
```

Çıktı: `✓ youtube: ready` + ilk video öneri görünecek.

---

## 2. 📅 Google Calendar API (Ücretsiz)

### Adımlar (10 dakika — biraz daha detaylı)

1. **Aynı Google Cloud Console projesinde**:
2. **Calendar API'yi etkinleştir**:
   - **"API'ler ve Hizmetler" → "Kütüphane"** → `Google Calendar API` → **"ETKİNLEŞTİR"**
3. **Service Account oluştur** (kullanıcı değil, kurum hesabı gibi):
   - **"API'ler ve Hizmetler" → "Kimlik Bilgileri"**
   - **"KIMLIK BİLGİLERİ OLUŞTUR" → "Hizmet Hesabı"**
   - Ad: `fermat-ai-calendar`
   - Rol: **"Düzenleyici" (Editor)** — gerekli değilse atlanabilir
   - **"BİTTİ"**
4. **JSON anahtarı indir**:
   - Oluşturulan service account'a tıkla → **"Anahtarlar"** sekmesi → **"ANAHTAR EKLE" → "Yeni anahtar" → JSON**
   - JSON dosyası bilgisayara iner. *Güvenli yerde sakla!*
5. **Dosyayı projeye yerleştir**:
   - Örnek konum: `C:\Users\zekig\OneDrive\Desktop\FermatAI\secrets\gcal.json`
   - `.gitignore`'a eklenmiş (git'e kaçmaz)
6. **Takvim paylaş** (kritik!):
   - Google Calendar'ı aç → Ayarlar → Ekleyeceğin takvim
   - **"Belirli kişilerle paylaş"** → service account email (JSON içinde `client_email` alanı, `fermat-ai-calendar@xxx.iam.gserviceaccount.com` gibi)
   - **İzin: "Etkinliklerde değişiklik yapma"**
7. **Takvim ID bul**:
   - Takvim ayarları → aşağıda **"Takvim Kimliği"** bölümü
   - `primary` (ana takvim) veya `abc123@group.calendar.google.com`

### .env'e ekle

```bash
GCAL_SERVICE_ACCOUNT_JSON=C:\Users\zekig\OneDrive\Desktop\FermatAI\secrets\gcal.json
GCAL_CALENDAR_ID=primary
# Veya:
# GCAL_CALENDAR_ID=fermat_etut_takvimi@group.calendar.google.com
```

### Test

```bash
.venv/Scripts/python.exe external_apis.py
```

Çıktı: `✓ google_calendar: ready`

---

## 3. 🎙 OpenAI Whisper (Zaten varsa .env'de OPENAI_API_KEY yeterli)

### Key kontrolü

```bash
# Mevcut mi bak:
grep OPENAI_API_KEY .env
```

- **VAR** ise — Whisper aktif, yapacak bir şey yok.
- **YOK** ise:
  1. https://platform.openai.com/api-keys
  2. "Create new secret key" → kopyala (`sk-...`)
  3. `.env`'e ekle:
     ```bash
     OPENAI_API_KEY=sk-...
     ```

### Maliyet
- Whisper-1: $0.006 / dakika (çok ucuz, 1 saat sesli mesaj = ~$0.36)

---

## 4. 📂 Anthropic Files API

### Durum
- `ANTHROPIC_API_KEY` zaten `.env`'de var → key gerekli değil
- SDK upgrade gerekebilir:
  ```bash
  .venv/Scripts/python.exe -m pip install --upgrade anthropic
  ```

---

## ⚙ `.env` Final Hali

```bash
# Mevcut
DATABASE_URL=postgresql://...
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
WA_TOKEN=...
WA_PHONE_ID=...

# 23 Nisan YENİ — Jarvis paket
YOUTUBE_API_KEY=AIzaSyA...senin_keyinler...
GCAL_SERVICE_ACCOUNT_JSON=C:\Users\zekig\OneDrive\Desktop\FermatAI\secrets\gcal.json
GCAL_CALENDAR_ID=primary

# Whisper model (opsiyonel, default whisper-1)
WHISPER_MODEL=whisper-1
```

---

## ✅ Doğrulama

Key'leri ekledikten sonra:

```bash
cd eyotek_agent
.venv/Scripts/python.exe external_apis.py
```

Beklenen çıktı:
```
=== API Status ===
  ✓ youtube: ready
  ✓ google_calendar: ready
  ✓ anthropic_files: ready
  ✓ whisper: ready

🎥 YouTube test: 2 video
  • Türev Nedir? Anlık Değişim [Tonguç Akademi]
  • ...

📅 GCal test: 3 upcoming event
```

Sonra bridge restart — **yeni tool'lar tam aktif:**

```bash
# Bridge restart
taskkill //F //PID <bridge_pid>
.venv/Scripts/python.exe -m uvicorn whatsapp_bridge:app --host 0.0.0.0 --port 8001 > logs/wp_bridge.log 2>&1 &
```

---

## 🚨 Güvenlik

- `secrets/gcal.json` → **.gitignore**'a ekle (zaten ekli olmalı)
- `.env` → git'e ASLA push etme
- YouTube API key'i paylaşma — başkası kullanırsa kota dolar

---

## 💡 Test Komutları (WA'dan)

Key'ler aktif olunca WhatsApp'tan:

- Öğrenci: `"türev konusu için video öner"` → YouTube Tonguç/Hocalara Geldik önerisi
- Öğretmen/Admin: `"Ahmet'e yarın 14:00 fizik etüt yaz"` → hem Eyotek'e yazar hem takvime ekler
- Admin: `"jarvis"` → sabah brief + API status dahil

---

## 📞 Sorun

- YouTube `403 quotaExceeded` → 10K/gün aşıldı, ertesi gün sıfırlanır
- GCal `403 insufficient permissions` → service account'u takvime paylaşmayı unutmuşsun
- `ModuleNotFoundError: google.oauth2` → `pip install google-auth google-api-python-client`
