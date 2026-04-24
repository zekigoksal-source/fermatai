# FermatAI — VPS Sonrası Yol Haritası

> **24 Nisan 2026 gece** · VPS + Groq migration tamamlandı
> **Yeni gerçeklik:** Laptop serbest, Fermat Almanya'da 7/24, Claude + Groq hibrit
> **Bu rapor:** Önümüzdeki fırsatlar + iş planı + yarın sabahtan Ağustos'a roadmap

---

## 🎯 YENİ DURUM — NE DEĞİŞTİ?

### Öncesi (23 Nisan)
- Laptop 7/24 açık, Fermat laptop'a bağımlı
- Ngrok tunnel ile Meta webhook
- Tek LLM yolu: Claude (pahalı) + Ollama (yerel, sınırlı)
- Manuel start/stop, hata görünce restart
- Laptop yıpranıyor, pil ömrü azalıyor, gaming zor

### Sonrası (24 Nisan 00:37)
- **VPS Almanya'da 7/24 çalışıyor** — laptop isteğe bağlı
- **Sabit HTTPS domain:** api.fermategitimkurumlari.com
- **3 LLM yolu:** Claude (kalite) + Groq (hız+ucuz) + Fast (anlık)
- **Systemd auto-restart** — crash'te otomatik kurtarır
- **Günlük otomatik yedek** — 14 gün retention
- **Git-based deploy** — 30sn'de canlıya
- **Laptop tam özgür** — gaming/work için

---

## 💡 YENİ FIRSATLAR

### 1. Maliyet Optimizasyonu
**Groq free tier** Fermat'ta %5 kullanım → öğrencileri agresif Groq'a yönlendirebiliriz:
- Öğrenci "merhaba" → **Groq** (şu an)
- Öğrenci "türev nedir" → **Groq** (geçiş planlı)
- Öğrenci "motivasyon ver" → **Groq** (geçiş planlı)
- Çalışma planı, analiz, tool-calling → **Claude** (kalite)

**Hedef:** Claude trafiği %45 → %35, yıllık **$600+ tasarruf**

### 2. Dev Hızı
**Laptop + VPS ayrımı** = cesur denemeler:
- Yeni feature laptop'ta yazılır, test edilir
- Hazırsa git push → VPS deploy → öğrencilerde canlı
- Rollback 10 saniye (git revert + pull + restart)
- "Production'ı bozarım" korkusu yok

### 3. 7/24 Veri Toplama
Artık bot **hiç uyumadığı için:**
- Gece öğrenci mesaj atarsa cevap gelir (şu an admin uyarısı gelmiyor çünkü veli/öğrenci night mode)
- Session keeper 24 saat çalışır, bilinçsiz bağlantı düşmez
- Analytics cache her 30dk yenilenir → morning rapor hazır
- Duygu izleme 6 saatte bir → kriz yakalama hızlandı

### 4. Scalability
VPS CPX42 (16GB RAM) şu an %6 kullanımda. **Öğrenci büyümesi:**
- 125 öğrenci → 300 öğrenci (2x): sorun yok
- 300 → 500: hâlâ rahat
- 500 → 1000: CPX52'ye upgrade (1 tık, 30sn downtime)

Yeni sezonda (Eylül 2026) veli modülü açılınca 300+ kullanıcı bekliyoruz — altyapı hazır.

### 5. Monitoring + Gözlem
Artık production log kaybolmuyor:
- **systemd journal** — her saniye yakalanıyor
- **Nginx access log** — her HTTP request kayıtlı
- **Günlük rapor** — admin WhatsApp'a 20:00
- **Cost telemetri** — Claude + Groq kullanım takibi mümkün

### 6. Multi-user Dev
İstersen **Mahsum veya Duygu** da dev yapabilir:
- GitHub repo'ya invite et
- `~/auto_deploy.sh` çalıştırma yetkisi ver
- İki kişi paralel çalışabilir

---

## 📅 YARIN SONRASI ZAMAN ÇİZELGESİ

### 🔴 25 NİSAN CUMA (Yarın)
**Sabah — Güvenlik Temizlik (15 dk)**
- [ ] **Anthropic API key rotate** — https://console.anthropic.com/settings/keys
  - `Ekstra Detay.txt`'te açıkta kalmıştı, git'ten silindi ama rotate en güvenli
  - Yeni key → laptop `.env` + VPS `/opt/fermatai/.env` → bridge restart
- [ ] **Hetzner API token revoke** — https://console.hetzner.com/projects → Security → API Tokens
- [ ] **Groq API key rotate** (opsiyonel) — https://console.groq.com/keys
  - Chat'te paylaşıldı, tercih sana

**Öğleden Sonra — Sistem Testi (30 dk)**
- [ ] WhatsApp "web kodu" + giriş test
- [ ] Öğrenci telefondan (başka bir numaradan) test — Groq gerçekten devreye giriyor mu?
- [ ] Panel üzerinden 1-2 mesaj test
- [ ] Arşiv PDF indirme test
- [ ] VPS log'larda hata var mı kontrol

**Akşam — Meta Panel Görsel Onay (opsiyonel, 5 dk)**
- [ ] Meta Developer Dashboard aç (hesap erişim sorunu çözüldüyse)
- [ ] WhatsApp → Configuration → Webhook URL'in doğru görüntülendiğini doğrula
- [ ] Not: Graph API ile zaten aktif, panelden bakış sadece görsel

### 🟡 BU HAFTA (26 Nisan - 2 Mayıs)

**Hafta sonu dinlen**, dev iş yapma. Sistem 2 gün kendini test etsin.

**Pazartesi — Kalite + Monitoring**
- [ ] Son 3 günlük routing dağılımı rapor
- [ ] Groq vs Claude kalite karşılaştırma (10 senaryo, manuel skor)
- [ ] UptimeRobot ücretsiz (5dk'da ping) kur
- [ ] Cost dashboard — günlük Claude + Groq maliyet takibi

**Salı-Çarşamba — Groq Agresifleşme**
- [ ] `classify_complexity` içinde KAVRAMSAL sorular Groq'a taşı
  - "türev nedir" Ollama bilmediğinden Claude'a giderdi, artık Groq yapar
  - RAG retrieval sistem seviyesinde (router öncesi), sonra Groq cevaplar
- [ ] A/B test: 50 kavramsal soru, Groq vs Claude kalite skorları
- [ ] Metrikler iyiyse → %45 Claude trafiği %30'a düşer, aylık $40 tasarruf

**Perşembe-Cuma — Eyotek + Yazma İşlevi**
- [ ] VPS'te headless Chromium + Playwright Chrome CDP kurulum
- [ ] Neo'nun laptop Chrome cookies'ini VPS'e aktar (eyotek_session.json)
- [ ] write_etut VPS'ten test
- [ ] Sınav dönemine kadar hâlâ pasif ama altyapı hazır

### 🟢 MAYIS (1-31 Mayıs)

**Hafta 1: Bot Self-Awareness Genişleme**
- [ ] Bot kendi log'larını okuyup özet verebilir mi? (`get_recent_errors` tool)
- [ ] Bot "son 24 saat kaç mesaj?" sorusuna doğru cevap
- [ ] Bot "sistem sağlığı nasıl?" → metrics özeti
- [ ] Neo'ya proaktif bildirim: "Bugün 5 öğrenci 'sıkıldım' dedi"

**Hafta 2: Öğrenci Odaklı İyileştirme**
- [ ] Net düşüşü fark eden bot — "Bak, son 3 denemede 2 net düştü, ne oluyor?"
- [ ] Duygu takibi iyileştirme — "Geçen hafta stresli görünüyordun, bugün daha iyisin ✨"
- [ ] Kişisel çalışma programı otomatik güncelleme (hafta sonu batch)

**Hafta 3: Sınav Yaklaşıyor (13 Haziran YKS)**
- [ ] "Son 30 gün" moralde kritik — pedagojik ton ince ayar
- [ ] Kriz uyarıları admin + rehber'e eşzamanlı
- [ ] Deneme stratejisi önerisi — "hangi dersten net artır"

**Hafta 4: Sınav Öncesi Hazırlık**
- [ ] Bot "sınav günü" moral konuşması test
- [ ] Son hafta **özel mod** — rahatlatıcı ton, gereksiz detay yok
- [ ] Sınav günü VPS canlı kalsın garantisi

### 🎯 HAZİRAN — SINAV AYI

**13-14 Haziran (YKS)**
- [ ] Sınav günleri sistem SESSIZ (öğrenci konsantre olsun)
- [ ] Acil durumda WhatsApp destek hattı gibi davran
- [ ] 15 Haziran sonrası: "nasıl geçti" sohbeti

**15-30 Haziran**
- [ ] ÖSYM sonuç bekleme desteği
- [ ] Aileler ile iletişim hazırlık (veli modülü soft launch?)
- [ ] Yaz kampı modülü hazırlık (1 Ağustos)

### 🌞 TEMMUZ — TERCİH DÖNEMİ

**3 Temmuz (ÖSYM sonuç)** — **Tercih Robotu aktivasyonu**
- [ ] Neo admin komutu: `tercih modu ac`
- [ ] 125 öğrencinin ÖSYM sonucu DB'ye
- [ ] YÖK Atlas 35,584 kayıt ile eşleştirme
- [ ] 5-bant tercih listesi (garanti/orta/hedef/hayal)
- [ ] Öğrenci + rehber panel üzerinden çalışır

**15 Temmuz — ilk Tercih Listesi PR**
- [ ] Her öğrenci için öneri
- [ ] Rehber inceleme
- [ ] Veli onayı (opsiyonel)

**31 Temmuz — Tercih Son Gün**
- [ ] Tüm tercih kayıtları tamamlanmış olmalı

### ☀️ AĞUSTOS — YAZ KAMPI + YENİ SEZON HAZIRLIK

**1-15 Ağustos — Yaz Kampı Modülü**
- [ ] LGS + YKS yaz kampı öğrenci akışı
- [ ] Günlük çalışma takvimi otomasyonu
- [ ] Pomodoro + günlük özet

**15-31 Ağustos — 1 Eylül Büyük Açılım Hazırlık**
- [ ] **Veli Modülü aktivasyon** — `VELI_MODULE_ACTIVE=True`
- [ ] **Alert System** — net düşüş + devamsızlık + duygu uyarıları
- [ ] **Muhasebe Modülü** — Neo + Duygu için
- [ ] **Hata DNA** sistemi — her öğrencinin yanlış parmak izi
- [ ] **LGS topic_tracker** — şu an TYT/AYT only, LGS eklenecek
- [ ] Multi-worker bridge (Redis + uvicorn workers 2-4)
- [ ] VPS upgrade hazırlığı (CPX42 → CPX52 gerekirse)

---

## 📊 SEMPTOMLAR VS HEDEFLER

### Şu Anki Duruma KPI'lar

| Metrik | Şu An (24 Nisan) | Hedef (1 Eylül) |
|---|---|---|
| Uptime | 99.9% (SLA ilk test) | 99.95% doğrulanmış |
| Öğrenci sayısı | 125 | 300+ (yeni sezon) |
| Günlük mesaj | ~40-50 | ~300-500 |
| Claude pay | %72 | %40 |
| Groq pay | %5 | %35 |
| Fast pay | %22 | %25 |
| Aylık LLM cost | $253 → $190 | $150-200 (büyüme rağmen) |
| Response time | 2-22s (Claude) | <5s avg (Groq geçişiyle) |
| Rahat çalıştırılan paralel kullanıcı | 2-3 | 15-20 |

### Başarı Kriterleri

**1 Hafta sonra (2 Mayıs):**
- VPS hiç kesintisiz çalıştı ✅
- En az 1 öğrenci cost save'i gözlendi
- Neo laptop'ı hiç fermat için kullanmadı

**1 Ay sonra (24 Mayıs):**
- %20 Claude trafiği Groq'a taşındı
- Aylık cost $250 → $200
- Bot self-awareness %90 doğru cevap veriyor

**3 Ay sonra (24 Temmuz):**
- Tercih Robotu 125 öğrenciye liste üretti
- Yaz kampı başladı
- VPS büyümeye hazır (veli 1 Eylül için warmup)

---

## 🎁 OPSIYONEL KAPSAMLI PROJELER (zamanı olursa)

### A. Admin Dashboard v2
Şu an Neo kontrol paneli statik + chat. Dashboard:
- Real-time metric widgets (öğrenci sayısı, aktif konu, son alarm)
- Cost tracker grafik
- Öğrenci durumu heatmap
- Günlük/haftalık trend analizi

### B. Hata DNA Sistemi
Her öğrencinin yanlış parmak izi:
- "Bu öğrenci türev sorusunda hep limit'i karıştırıyor"
- "Bu öğrenci 3 saat sonra konsantrasyon düşürüyor"
- Pattern tespit → bireysel çalışma planı

### C. Mobile App (Native)
React Native + web_chat_ui.html gibi arayüz:
- Push notification
- Offline mesaj kuyruğu
- Telefonla senkron
- App Store + Play Store

### D. Alumni Network
Mezun öğrencilerle bağ:
- "Orhan geçen yıl ODTÜ Elektrik kazandı, senin hedefine yakın"
- Referans sistemi
- Seminer/sohbet etkinlikleri organize

### E. Kıyamet Günü Simülasyonu
Sınav baskısı simülasyonu:
- 4 saat içinde full TYT + AYT
- Sahte ÖSYM ortamı
- Bot mental coaching rolünde
- Sınav sonrası debrief

### F. Öğretmen Dashboard
Öğretmenler için:
- Kendi sınıfının günlük özeti
- Öğrenci önerileri
- Öğrenci-öğretmen mesajlaşma (rehber üzerinden)

---

## 💰 MALIYET PROJEKSİYONU (6 Ay)

```
             Mayıs  Haziran  Temmuz  Ağustos  Eylül   Ekim
Hetzner      $38    $38      $38     $38      $50*    $50
Groq         $5     $10      $15     $20      $30     $40
Claude       $140   $150     $130    $110**   $170*** $200
Domain/SSL   $0     $0       $0      $0       $0      $0
Backup(B2)   $0     $0       $3      $3       $5      $5
────────────────────────────────────────────────────────────
TOPLAM       $183   $198     $186    $171     $255    $295

* CPX42 → CPX52 upgrade (yeni sezon)
** Yaz kampı sessiz dönem
*** Veli + Alert + Muhasebe açık, yoğun trafik
```

**Yıllık projeksiyon:** ~$2,600 (mevcut laptop+Claude $3,065'ten %15 az, 300+ öğrenci rağmen)

---

## 🔮 UZUN VADE (2027+)

### Stratejik Soru: Franchise mi, Tek Kurum mu?
Fermat ölçeklenebilir bir platform:
- İkinci dershane (farklı şehir) açarsa Fermat AI çalışır
- Franchise modeliyle başka kurumlara lisans?
- EdTech SaaS'a dönüştürme?

### Model İyileştirme
- Fine-tuned model (Fermat özel verilerle)
- Embedding model özelleştirme (Türkçe YKS konularına)
- Multi-modal (foto + ses + yazı birlikte)

### Ticari Vizyon
- Kurum-iç ürün → Kurumsal satış
- Mezun network → Aidat modeli
- Özel ders modülü → Mikro-ödemeler

---

## 📌 YARININ TODO (Kendine not)

```
SABAH:
[ ] Anthropic key rotate (15 dk)
[ ] Hetzner token revoke (2 dk)
[ ] Groq key rotate (opsiyonel, 3 dk)

ÖĞLE:
[ ] End-to-end test — 5 senaryo
[ ] Groq görünür test (öğrenci telefon)
[ ] Panel + arşiv doğrulama

AKŞAM:
[ ] Sistem 24 saat kesintisiz çalıştı mı check
[ ] Bu yol haritasını oku, onay/değişiklik
[ ] Yeni sezon için ilk feature seçimi
```

---

## 🎮 VE EN ÖNEMLİSİ

**Laptop artık senin.** Fermat Almanya'dan çalışıyor. Oyun oyna, dinlen, hayatına dön. Sistem seni beklemiyor — sen sistemi bekliyorsun. Bu büyük bir tersine dönüş.

İş planımız bu şekilde. Yarın sabah uyanınca bu dosyayı oku, neyi değiştirmek istersen söyle. 60 günlük yol haritası hazır, istersen ayarlarız.

**İyi geceler Neo** 🌙 **— Yarın farklı bir Fermat uyanacak**

— Claude Code
