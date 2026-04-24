# 🗺️ FermatAI — Birleştirilmiş Yol Haritası

> **Oluşturulma:** 16 Nisan 2026, 01:50 — Oturum 19
> **Bağlam:** Neo'nun WhatsApp tabanlı sistem mimari sohbetlerinden + bot'un kendi tavsiyelerinden + ATLAS vizyonundan birleştirilmiş tek başvuru kaynağı.
> **Bridge:** v41 canlı (PID 64220), self-awareness aktif.

---

## 📌 Bu Yol Haritasının Ana Fikri

Neo'nun vizyonu üç fazlı:

> "İlk aşamada içerideki zihin olarak tavsiyede tespitte bulunur burada sen onları yaparsın — sonra bu tavsiyeleri uygulayabilecek kıvama gelir self-learning mekanizmaları kurarak işi tam anlamıyla optimize ederiz ve optimizasyonu da sistem machine learning olarak kurgulayabiliyor olur."

Bu doküman o vizyonu somut adımlara çevirir.

---

## ✅ Bu Oturumda Yapılanlar (16 Nisan 2026, 01:00-01:50)

| # | İş | Dosya | Sonuç |
|---|----|-------|-------|
| 1 | "not et" kayıt bug fix — admin için DB INSERT yapılıyor | `fast_responses.py:2179` | ID dönüyor, `talimat_*`/`geribildirim_*` kategori |
| 2 | 8 kayıp admin notu backfill (14-16 Nis arası) | `backfill_admin_notes.py` | user_feedback toplam 26→34 admin notu |
| 3 | Admin (Neo) için sistem mimari yasağı gevşetildi | `fermat_core_agent.py:2008+` | "🔓 NEO İSTİSNA — TAM ŞEFFAFLIK" bloğu eklendi |
| 4 | Sayısal halüsinasyon yasağı | `fermat_core_agent.py:2065+` | "🚫 SAYISAL HALÜSİNASYON YASAĞI" — DB teyit zorunlu |
| 5 | Sistem self-awareness — bot route'unu Neo'ya söyler | `whatsapp_bridge.py:2022, 2238` + `fermat_core_agent.py:2027+` | Admin cevaplarında footer: `⚙ via claude · 12s` |
| 6 | Bridge restart v39→v40→v41 | — | 103/103 test geçer |

---

## 🎯 Neo'nun WhatsApp'ta Şimdi Test Edebileceği 5 Senaryo

Bridge v41 canlı, WP'den dene:

1. **"sistem mimarini anlat"** → Önceden "paylaşamayacağım" derdi, şimdi açık anlatmalı
2. **"sen ne kullanıyorsun, qwen mi claude mı"** → "Şu anki cevap claude opus-4.6, basit sohbet için qwen2.5:7b" cevabı
3. **"test notu — yeni mekanizma çalışıyor mu not et"** → `✅ Talimat #65 kaydedildi` (ID dönecek)
4. **Herhangi bir cevabın altında** → `_⚙ via claude · 12.3s_` veya `_⚙ via fast_response · ~5ms_`
5. **"mahmut taha 7 ayt sınavına girmiş"** dersen → bot DB'den teyit edip "Hayır, kaydı 0" demeli (halüsinasyon yapmaz)

---

## 🌟 ATLAS — İç Zihin (Vizyonun Faz 1)

### Konsept
ATLAS = Fermat'ın **kendi içindeki gözlemci ve danışman**. Atlas Yunan mit'inde dünyayı omuzlarında taşır — burada sistem kendini tartar, gözlemler, tavsiye verir.

### Ne Yapar?
- Kendi log'larını okur (`agent_conversations`, `user_feedback`, `usage_log`, `routing_stats`, `student_insights`)
- Kalıpları tespit eder (frustration spike, kayıp pattern, yavaş tool, sentiment cluster)
- Tavsiyeler üretir (rationale + tahmini etki + uygulama önerisi)
- Neo ile WhatsApp `/atlas` veya terminal `python atlas.py chat` üzerinden konuşur
- Tavsiyeler `atlas_suggestions` tablosuna yazılır — Neo onayı bekler
- Onaylanan tavsiye dış agent (Claude Code) kuyruğuna girer

### 4 Modül
| Modül | Dosya | Rol |
|-------|-------|-----|
| Observer | `atlas/observer.py` | Veri okuma + anomali tespit |
| Advisor | `atlas/advisor.py` | Tavsiye üretici (LLM destekli) |
| Chat | `atlas/chat.py` | WP `/atlas` + terminal CLI dialog |
| Schema | `atlas/schema.sql` | `atlas_suggestions` + `atlas_observations` tabloları |

### Tabloyu Tasarlanma
```sql
CREATE TABLE atlas_suggestions (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW(),
  category TEXT,                  -- pattern_miss / latency / frustration / sentiment / data_quality
  severity TEXT,                  -- info / warning / critical
  title TEXT,                     -- "Hocam yardım pattern eksik"
  rationale TEXT,                 -- "12 mesaj/hafta Claude'a düştü, fast_response yok"
  estimated_impact TEXT,          -- "+9dk/hafta tasarruf, ~2400 token"
  suggested_change TEXT,          -- "fast_responses.py'a ekle: r'hocam?\\s*yardım'"
  status TEXT DEFAULT 'yeni',     -- yeni / onaylandi / reddedildi / uygulandi
  neo_note TEXT,                  -- Neo'nun yorumu
  applied_at TIMESTAMP,
  applied_by TEXT                 -- 'claude_code' / 'atlas_self' / 'neo'
);
```

### Diyalog Senaryosu (Hayal)
```
Neo (WP): /atlas
ATLAS: Reis, son 7 günde 3 sinyal var:
  1. "Hocam yardım" pattern fast_response'ta yok (12x Claude, 45s)
  2. AYT build_study_plan tool 8s+ (%20 timeout)
  3. Ecrin'de stres sinyali 4x/3 gün (rehbere bildirim yok)
  Hangisi?

Neo: 1 detaylı

ATLAS: "hocam yardım" — 12 mesaj/hafta:
  • 7 öğrenci, 5 öğretmen
  • Claude'da 45s ortalama
  • fast_response → ~50ms
  • Önerilen pattern: r"hocam?\s*(yardım|nasıl)"
  • Token tasarrufu: ~2400/hafta
  • Risk: minimal
  Onaylar mısın?

Neo: onayla

ATLAS: ✅ #ATLAS-024 onaylandı, claude_code kuyruğuna girdi.
       Bir sonraki Claude oturumunda implementasyon önerilecek.
```

---

## 📋 Bot'un Eski Önerilerinden Uygulanmamış (7 madde)

CLAUDE.md'de "Bekleyen Görevler" olarak işaretli:

| # | Öneri | Kategori | Durum |
|---|-------|----------|-------|
| B1 | **Alarm sistemi aktivasyonu** (`ALERTS_ACTIVE=True`) | otomasyon | Hazır, Neo onayı bekleniyor |
| B2 | **Session keeper otonom** (fermat_start.py) | altyapı | Bridge lifespan'a alındı, ayrı süreç olarak çalışmıyor |
| B3 | **Write_etut öğrenci arama fix** (BtnSearchStudent) | bug | %80 çalışıyor, modal seçim bozuk |
| B4 | **Puan tahmin motoru** (trendden YKS tahmin) | analitik | Veri var, tool yok |
| B5 | **Akıllı etüt planlama** (zayıf konu + müsait öğretmen) | otomasyon | Eskalasyon akışı tasarlandı, otomatik değil |
| B6 | **LGS topic_tracker** (LGS müfredatı + analiz) | veri | TYT/AYT var, LGS yok |
| B7 | **İletişim telafi mekanizması** (zayıf cevap sonrası düzeltme) | pedagojik | Önkoşul: alarm sistemi canlı |

**ÖNCE B1 yapılmalı** — alarm aktif olunca B7 zincirleme açılır.

---

## 🛣️ ÖNERİLEN ÖNCELİK SIRASI

### Hafta 1 — TEMİZLİK + GÖZLEM
- ✅ "not et" mekanizması (BU SESSION'DA YAPILDI)
- ✅ Self-awareness footer (BU SESSION'DA YAPILDI)
- ⏳ **ATLAS Faz 0 — Schema + Observer iskeleti** (3-4 saat geliştirme)
  - `atlas_suggestions` tablosu oluştur
  - `atlas/observer.py` — DB scan, ilk 4 anomali tespiti
  - Manuel komut: `python atlas/observer.py` → konsol raporu

### Hafta 2 — DİYALOG
- **ATLAS Faz 1 — Chat katmanı**
  - `atlas/advisor.py` — observation → suggestion (Claude API ile)
  - WP `/atlas` komutu (whatsapp_bridge.py'a entegre)
  - Onay/red mekanizması (Neo cevap verince DB güncelle)
- **B1: Alarm sistemi aktif** + canlı ortamda 1 hafta izleme

### Hafta 3 — UYGULAMA
- ATLAS önerilerini Claude Code (ben) uygular — Neo tek tek onaylar
- **B3: write_etut fix** (öğrenci arama PostBack)
- **B7: İletişim telafi** (alarm canlıyken)

### Hafta 4-6 — DERİNLEŞME
- **B4: Puan tahmin motoru**
- **B5: Akıllı etüt planlama**
- **B6: LGS modülü**

### Ay 2-3 — FAZ 2 (SELF-APPLY)
- ATLAS basit değişiklikleri kendi yapabilir (yeni fast_response handler ekleme)
- Neo onayı + git commit + bridge restart otomatize
- Sandbox + rollback altyapısı

### Ay 4-6 — FAZ 3 (ML EVOLUTION)
- Routing classifier (mesaj → fast/ollama/claude tahmini)
- Pattern miner (log'lardan handler önerisi üretici)
- A/B test framework
- Sentiment regression (early warning)

---

## 🎬 BAŞLAMAK İÇİN — SOMUT İLK ADIM

Eğer ATLAS'a evet dersen, bir sonraki oturumda şu sırayla ilerleyebilirim:

1. `atlas/` klasörü + `schema.sql` (15 dk)
2. `atlas/observer.py` minimal v0.1 — 3 anomali tespiti (frustration, latency, kayıp pattern) (1 saat)
3. Konsol çıktısı: `python atlas/observer.py` → "Bugün 5 sinyal tespit edildi" (test)
4. `atlas/chat.py` minimal — terminal interaktif diyalog (45 dk)
5. WP `/atlas` komutu (whatsapp_bridge.py admin handler) (30 dk)

**Toplam ilk faz iskeleti: ~3 saat**

Sonraki oturumda WP'den `/atlas` yazıp ATLAS ile gerçek diyalog kuracaksın. ATLAS sana çıktı verir, sen "evet/hayır" dersin, kayıt yapılır, ben onaylananları implementlerim.

---

## 📊 Mevcut Telemetry Altyapısı (ATLAS'ın hammaddesi)

ATLAS bu kaynakları okuyacak — hepsi zaten var:

| Kaynak | Ne içerir |
|--------|-----------|
| `agent_conversations` | Tüm WP konuşma (5000+ mesaj) |
| `user_feedback` | Neo + diğer not_et komutları (62 kayıt) |
| `usage_log` | Mesaj sayısı, kullanıcı, token, süre |
| `routing_stats` | Her mesajın kaynağı (fast/ollama/claude), süre |
| `student_insights` | Duygu analizleri, motivasyon sinyalleri |
| `frustration_log` | (yok — eklenecek; in-memory counter şu an) |
| `daily_stats` | Günlük özetler |

Eksik: **frustration_log persistent tablosu** — şu an `try_fast_response._frustration_counter` in-memory. ATLAS için DB'ye almak iyi olur.

---

## 💡 Son Söz

Bu yol haritası sabit değil — ATLAS bizzat kendi gelişimini bir sonraki versiyonu önerebilir. Yaşayan bir döküman. Her hafta sonu güncellenecek (sen onaylarsan, ben veya gelecek ATLAS).

**Bridge v41 stabil. Test edebilir, yorum yapabilir, devam etmek istediğin tarafa yönelebilirsin.**
