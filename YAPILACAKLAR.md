# FermatAI — Yapılacaklar Listesi

> Son güncelleme: **14 Nisan 2026, 23:25**
> Önceki güncel: bkz CLAUDE.md "Bekleyen Görevler" bölümü

---

## 🚨 23:25 GÜNCELLEMESİ — Konuşma Analizi Sonrası 5 Kritik Bulgu

### Bulgu 5: YKS Sekmesi Tıklama Bug — 2 Ay Veri Kaybı (FIX'lendi) 🔥

**Sorun:** `sync_exams.py` YKS sekmesini bulup tıklıyordu ama:
- SPAN'a tıklıyordu (Bootstrap nav-tabs için yetersiz, A elementine tıklamalı)
- Tüm tabloyu okuyordu (TYT/YKS/Tüm Sınavlar sekmelerinin satırları karışıyordu)
- Katılım tespiti "Katıldı" kelimesi arıyordu — ekranda **karne ikonu** var, kelime yok

**Sonuç:** 95+ öğrencinin AYT verisi DB'ye gelmiyordu. Taha gibi 12.SAY öğrenciler için
puan tahmin yanlış çıkıyordu (TYT bazlı ~390 ham puan).

**Fix (sync_exams.py:108):**
1. `ul.nav-tabs > li > a` selector ile doğru tab elementine tıkla
2. Aktif `.tab-pane` içindeki tabloyu oku (`offsetParent !== null` filtresi)
3. Katılım: son hücrede icon (img/svg/a) varsa `katildi`, yoksa text "Katılmadı" kontrolü

**Doğrulama (Taha — soz_no 182):**
- TYT: 23 toplam, **15 katildi**, 8 katilmadi ✅
- YKS: 7 toplam, **2 katildi**, 5 katilmadi ✅ (ekrandakine birebir uyumlu)

**Aksiyon:** `sync_exams.py --full` arka planda çalışıyor — 95+ öğrenci AYT verisi geliyor.

---

## 🚨 23:15 GÜNCELLEMESİ — Önceki 4 Kritik Bulgu

### Bulgu 1: Filler ATILMAMIŞ — Anthropic SDK SYNC (FIX'lendi)
- **Kök sebep**: `Anthropic` (sync) SDK kullanılıyordu, `client.messages.create()` SYNC HTTP
  → event loop'u bloke ediyordu → `asyncio.create_task(_watchdog())` çalışamıyordu
- **Fix**: `fermat_core_agent.py:2933`, `whatsapp_bridge.py:744`, `llm_router.py:462` →
  hepsi `asyncio.to_thread(...)` ile sarmalandı
- **Beklenen**: artık 3sn sonra filler atılmalı (bridge restart sonrası)

### Bulgu 2: Intent Pattern ÇOK STRICT (FIX'lendi)
- "Taha icin durum nasıl gözüküyor", "kurum geneli son denemeleri ozetle" gibi
  doğal Türkçe cümleleri tanımıyordu → filler atılmıyordu
- **Fix**: `conversation_flow.py` pattern'lar genişletildi + generic fallback eklendi
  (20+ char + action verb içeren her mesaj long-intent kabul edilir)

### Bulgu 3: AYT Veri Eksikliği — 95+ ÖĞRENCİ (TODO)
- 120 öğrencide TYT verisi var, ama sadece **26 öğrencide AYT** verisi var
- **Taha (MAHMUT TAHA AKKAYA, 12 SAY)**, Mehmet Alp, Ecrin hariç tüm 12.SAY/EA/Mezun
- Eyotek'ten YKS sekmesi yeniden çekilmeli — `sync_exams.py --full` Chrome CDP açık iken
- **AKSIYON (kullanıcıya)**: Chrome CDP başlat (`chrome --remote-debugging-port=9222`),
  sonra bridge admin: `sync baslat` veya CLI: `python sync_exams.py --full`

### Bulgu 4: `sinav_adi` Kolon Hatası (FIX'lendi)
- `get_student_analytics` tool'u eski kolon adı kullanıyordu
- `student_exams` tablosu: `exam_name`, `exam_date`, `toplam`, `turkce`, `matematik` vs.
- **Fix**: `fermat_core_agent.py:507` doğru kolonlara mapland


---

## 🎯 ŞU AN NEREDEYİZ?

### Aktif Sistem Özeti
- ✅ **Bridge**: `localhost:8001` canlıda, ngrok ile WP webhook
- ✅ **DB**: PostgreSQL fermatai (118+ tablo, 4.500+ RAG kayıt, 7.300+ yoklama)
- ✅ **Ollama**: qwen2.5:7b (warmup'li), 5 model yüklü
- ✅ **Claude**: Sonnet 4, paralel tool_call (yeni)
- ✅ **Routing**: Fast %50 + Ollama %20 + Claude %30 (hedef)

### Bugün Tamamlanan İşler (14 Nisan 2026 — Oturum 16)

#### A) 7 Yeni Modül (Hafta 1-6 paralel plan)
| Modül | İşlev |
|-------|-------|
| `sync_attendance.py` | Yoklama scheduled sync (4× gün) |
| `self_observer.py` | **Faz 1** — kalite skoru + halüsinasyon flag |
| `self_diagnosis.py` | **Faz 2** — kök neden + çözüm önerisi |
| `topic_difficulty_map.py` | Kurum geneli konu zorluk haritası |
| `smart_etut_advisor.py` | Akıllı etüt: zayıf konu × öğretmen × slot × yoklama |
| `suggestion_engine.py` | **Faz 3** — `improvement_proposals` admin onaylı düzeltme |
| `puan_tahmin.py` | YKS resmi formül + trend + bölüm hedef analizi |
| `pdf_archive.py` | Aylık toplu PDF arşivi (`reports/YYYY-MM/`) |
| `foto_solver_v2.py` | Foto v2: zayıf konu eşleştir + RAG öner + dinamik limit |
| `pedagojik_koc.py` | Pomodoro / Feynman / günlük plan / koç istatistik |

#### B) UX Akıcılık Katmanı (Yeni)
- `conversation_flow.py` — long-intent detect + 35+ varyasyonlu filler + post-followup
- Bridge entegrasyon: 3sn watchdog (fast cevaplar etkilenmez, Claude cevapları öncesi filler)
- Per-phone async lock + queue: ardışık mesajlar çakışmaz, birikenler tek context'te merge
- Reaction (👍❤️) handling: log + sessiz, akışı bölmez

#### C) Hız İyileştirmeleri
- ✅ **Tool_call paralel** (`asyncio.gather`) — Claude path 29s → **17.4s** (%40 hızlanma)
- ✅ **DB pool altyapı** (`get_db_pool`, `db_fetch`, `db_fetchrow`) — 200-500ms tasarruf/mesaj
- ✅ **Ollama warmup** bridge boot'ta — cold start 6s yok
- ✅ `routing_stats` hata yutma fix (log eklendi)

#### D) Yeni PostgreSQL Tabloları
| Tablo | Açıklama |
|-------|----------|
| `quality_log` | Her cevap kalite skoru + halüsinasyon flag |
| `improvement_proposals` | **Faz 3** düzeltme önerileri kuyruğu |
| `foto_questions` | Foto çözüm geçmişi + zayıf konu eşleşme |
| `pedagojik_koc_log` | Pomodoro/feynman aktivite |

#### E) Test Sonuçları
- 14/14 modül **import OK**
- 10/10 modül **smoke test** geçti (0.27s paralel)
- 9/9 admin WP komut **uçtan uca OK**
- Concurrent test: 3 ardışık mesaj → 2 cevap (1+2 birleşik), kullanıcı bekletilmez

---

## 🔴 ACİL — Önümüzdeki 1-2 Hafta

### 1. Alarm Sistemi Aktifleştirme
- Şu an `ALERTS_ACTIVE = False` — Neo onayladıktan sonra `True` yap
- Cron kurulumu (günlük + haftalık)
- Test: 1 öğrenciye dummy alarm at, doğrulama
- **Risk**: yanlış pozitif rahatsız edebilir, ilk hafta dikkatli izle

### 2. Eyotek Session Drop Çözümü
- ASP.NET session ~20-30dk timeout — `session_keeper.py` aktif ama HTTP GET yetersiz
- **Önerilen**: CDP üzerinden gerçek sayfa navigate (3dk)
- `session_keeper.py` zaten CDP'ye geçirildi (Oturum 15) — fermat_start.py ile başlat
- Test: bir günlük canlı çalışma, kaç kez session drop

### 3. write_etut Öğrenci Arama Bug
- BtnSearchStudent PostBack new_page'de çalışmıyor
- Etüt yazma %80 OK, son adımda öğrenci listesi alınamıyor
- Çözüm: ya iframe içine bak ya da AJAX çağrısını manuel taklit et

### 4. PDF Kaynak Import Pipeline
- RAG sadece Claude-üretimi 36 konu + OGM Vision 390 cıkmış soru var
- Kullanıcının elindeki PDF'leri (yardımcı kaynak) RAG'a aktarma
- `pdf_importer.py` mevcut — ama otomatik klasör tarama eksik

### 5. Suggestion Engine Faz 4 (Otonomi)
- 3 öneri var şu an, hepsi `bekliyor`
- Admin onaylayınca **otomatik uygulama** yapılacak adım eksik
- En riskli kısım: kod değişikliği otomatik yapılırsa testler kırılabilir
- **Önerilen**: ilk versiyon "öneriyi clipboard'a kopyala + admin'e gönder" — manuel uygula

---

## 🟡 ORTA VADE — 2-4 Hafta

### 6. Web Tabanlı Chat Arayüzü (Neo'nun bugün eklediği)
**Neden:** WhatsApp "yazıyor..." göstergesi yok, streaming yok, markdown render zayıf
**Plan:**
- Faz 1: FastAPI + WebSocket + minimal HTMX (kurum içi)
- Faz 2: Mobile responsive
- Faz 3: Fermat brand uyumlu, rol bazlı paneller (öğrenci/öğretmen/admin farklı)
**Avantaj:** WhatsApp casual, web derinlemesine analiz

### 7. İletişim Telafi Mekanizması
- Zayıf cevap (frustration) sonrası telafi mesajı
- "Daha önce sordugun [X] hakkında seni daha iyi anlayabilirdim..."
- ÖNKOŞUL: alarm sistemi canlı + test edilmiş olmalı
- Test edilmediğinde yanlış zamanda mesaj atma riski yüksek

### 8. RAG Vision Import (Çıkmış Soru PDF)
- Mevcut: OGM Vision 390 sayfa imported (TYT + AYT Sayısal + AYT EA)
- Kalan: 2 kitap daha (TYT Din Kültürü, AYT Sözel-2 Din Kültürü)
- Maliyet: ~$4 (200 sayfa × $0.02)

### 9. Pedagojik Koç Aktif Kullanım
- Tablolar hazır, kod çalışıyor (test edildi)
- Öğrencilere duyuru: "pomodoro basla matematik" yazabilirsin
- 1 hafta canlı kullanım, geri bildirim al
- Genişletme: "günlük hatırlatıcı" — saat 19:00'da "bugün ne çalıştın?"

### 10. Veli Modülü (Eylül 2026'da)
- ⚠️ Bu sezon (Mayıs sonu) açılmayacak — Neo direktifi
- Kod hazır (`veli_module.py`, `VELI_MODULE_ACTIVE = False`)
- Eylül sezon başı: `True` yap + duyuru

---

## 🟢 UZUN VADE — 1-3 Ay

### 11. Adaptive Learning Faz 4-5
- Faz 4: kısmi otonomi (düşük riskli düzeltme öneri otomatik uygulanır)
- Faz 5: tam adaptive (öğrenci bazlı kişiselleşir, prompt dinamik)

### 12. Mezun Takip Sistemi
- Yerleşme sonuçları (Ağustos)
- Referans, sosyal medya içerik
- Otomatik tebrik + LinkedIn paylaşım önerisi

### 13. Öğretmen Dashboard (Web)
- Sınıf bazlı performans
- Etüt yapılan öğrenciler
- Net trendi grafiği

### 14. Konu Zorluk Haritası → Öğretmen Toplantısı
- `topic_difficulty_map.py` çıktısı Powerpoint'e otomatik
- Aylık öğretmen toplantısı için hazır slayt

---

## 🔧 BİLİNEN ZAYIF YÖNLER

| Sorun | Etki | Çözüm |
|-------|------|-------|
| Eyotek session drop 20-30dk | Yazma engellenir | CDP keep-alive (mevcut, fermat_start.py ile başlat) |
| Ollama cold start 6s | İlk mesaj yavaş | Bridge boot'ta warmup (eklendi 14 Nisan) |
| 28 yerde manuel `asyncpg.connect` | Mesaj başına 200-500ms kayıp | DB pool altyapı eklendi, gradual migration sırada |
| LGS topic_tracker yok | LGS öğrencilerine zayıf konu yok | LGS ders müfredatı manuel ekle |
| `routing_stats` boş | Routing dağılım istatistiği yok | Hata logu eklendi (14 Nisan), bridge restart sonra dolmaya başlamalı |
| Bazı öğrenci `class_name` yanlış format | "[10] 10 SAY A" prefix'li | Toplu DB temizliği gerek |
| Alarm sistemi pasif | Erken müdahale yok | Neo onayı bekleniyor |

---

## 📊 BUGÜNKÜ HIZ KAZANIMI ÖZETİ

| Path | Önce | Sonra | Kazanım |
|------|------|-------|---------|
| Fast cevap | 100ms | 100ms | — (zaten optimal) |
| Ollama (warm) | 6.93s | 6.02s | %13 |
| Claude (tool-call) | 29.20s | 17.40s | **%40** ⚡ |
| Concurrent mesaj | Çakışıyordu | Queue'da merge | Çakışma yok ✅ |

---

## 🎓 KULLANICI (NEO) ALACAĞI EYLEM

1. **Bridge'i restart et** — yeni paralel tool_call + DB pool + warmup için
   ```
   # Eğer fermat_start.py ile başlatılmışsa: Ctrl+C, tekrar başlat
   ```
2. **Test komutu**: WhatsApp'tan "kurum geneli son denemeleri ozetle" yaz, ~17sn'de cevap gelmeli
3. **Filler test**: "puan tahmin ecrin" yaz, 3sn'de filler + sonra ana cevap
4. **Concurrent test**: 2 mesaj art arda at, 2.sine "✋ Bu mesajini aldim..." dönmeli

---

## 📁 BUGÜN OLUŞAN DOSYALAR (eyotek_agent/)

```
sync_attendance.py        — Yoklama scheduled sync
self_observer.py          — Faz 1 kalite gözlem
self_diagnosis.py         — Faz 2 kök neden
topic_difficulty_map.py   — Konu zorluk haritası
smart_etut_advisor.py     — Akıllı etüt önerisi
suggestion_engine.py      — Faz 3 düzeltme önerisi kuyruğu
puan_tahmin.py            — YKS puan tahmin
pdf_archive.py            — Aylık PDF arşivi
foto_solver_v2.py         — Foto v2 (zayıf konu + cıkmış)
pedagojik_koc.py          — Pomodoro/Feynman/koç
conversation_flow.py      — UX akıcılık (filler + queue)
```

---

_Bu dosyayı `C:\Users\zekig\OneDrive\Desktop\FermatAI\YAPILACAKLAR.md` üzerinden takip et._
_Her iş tamamlandığında işaretle ve CLAUDE.md "Tamamlanan Görevler" bölümüne ekle._
