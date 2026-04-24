# 📅 FermatAI — Geliştirme Takvimi (20 Nisan 2026 toplantı çıktısı)

Neo-Bot-Claude Code arasında 3 turlu geliştirme toplantısının çıktıları + 8 test sonucu + Neo'nun 4 tespiti birleştirilerek.

---

## ✅ Test Sonuçları (20 Nisan, 8/8 GEÇTİ)

| Test | Durum | Not |
|------|-------|-----|
| Admin insight view (soz_no=174) | ✅ | İrem 7 insight, supersede çalıştı |
| Outreach queue | ✅ | 0 pending (guard çalışıyor) |
| Arşivden sohbet | ✅ | 20 mesaj → 960 char context |
| Mobil marka | ✅ | 3 breakpoint + animasyonlar |
| Chart buton payload | ✅ | Son 1200 char parent text geçiyor |
| Puan tahmin + hedef | ✅ | İrem ITU için 173 net gap |
| Insight backfill | ✅ | 26 öğrenci, 227 mesaj işlenebilir |
| OGM fast response | ✅ | 1-5ms latency |

---

## 🔍 İçeriden Tespit Edilen Problemler (Bot analizi)

### Kullanıcı Pattern'ları
1. **Görsel konu anlatımı eksik** — `send_exam_image` sadece OGM Vision için. Diagram/şema yok.
2. **"Anlat" x3 döngüsü** — Adaptive re-explain mekanizması yok (analoji→formül→örnek rotasyonu)
3. **Ollama frustration kaçışı** — "ChatGPT'ye gidiyom" Ollama path'inde kaldı, Claude'a eskale olmadı
4. **query_analytics bağımlılığı** — 731 çağrı vs get_student_analytics 88 (güven sorunu)
5. **Uzun plan kesilmesi** — 165+ satır plan "Bu p..." diye kesildi

### İç Mimari
6. **Rehber tool eksikliği** — `prepare_counsellor_brief` yok, 30sn yavaş
7. **Plan state yok** — her düzenleme sıfırdan (`student_active_plans` tablosu gerek)
8. **Öğretmen değer önerisi sıfır** — 30 günde 0 mesaj
9. **Ret → yönlendirme kopuk** — "telefon veremem ama etüt talebi iletebilirim" yok
10. **Transfer failure detection yok** — topic_tracker × student_exams cross-reference yapan tool eksik

### Gelecek + Optimization
11. **Veli bildirim motoru** — altyapı hazır, haftalık digest template yok
12. **Öğretmen "Sınıfım Bu Hafta"** — `get_class_brief(sinif, ders, tarih)` tool eksik
13. **Veri kalitesi audit** — class_name NULL, derslik D-1 her yerde, [AYT] prefix sahte kayıtlar, topic_tracker kolon adı yanlış
14. **Tool call latency** — student bazlı cache yok (5dk TTL)
15. **Frustration routing intercept** — Ollama path'inde keyword bazlı force-claude
16. **Uzun çıktı web'e yönlendirme** — 1800 char eşiğinde otomatik özet+link

### Neo'nun Tespitleri (bot konuşmasından)
17. **D-1 Dersliği çakışması** — 62 slot, 5 sınıf aynı anda (veri girişi hatası)
18. **Tercih listesi taslağı** — puan_tahmin var ama otomatik bölüm önerisi yok
19. **Whisper pipeline** — ödeme yapıldı, kod yazılmadı
20. **Frustration regresyon izleme** — kapanan vakalar gerçekten çözüldü mü?

---

## 🎯 Bot'un Önerdiği TOP 3 Acil

| Sıra | İş | Efor | Etki |
|------|-----|------|------|
| 🥇 | **Frustration → Claude routing intercept** | 2 saat | Anlık churn önleme |
| 🥈 | **`student_active_plans` tablosu + diff update** | 1 gün | Yaz kampında plan süresi 25s → 3s |
| 🥉 | **Data audit script (veri kalite temizliği)** | Yarım gün | Sonraki 1000 tool call güvenilirliği |

---

## 📅 TAKVİM

### Hafta 1 (21-27 Nisan 2026) — Hızlı Kazanç

**Pazartesi-Salı (21-22 Nis):** Acil 3 iş
- [ ] Frustration keyword intercept (routing_engine.py) — 2 saat
- [ ] `student_active_plans` tablo şeması + basit CRUD — 1 gün
- [ ] Data audit script yaz + çalıştır — yarım gün

**Çarşamba-Perşembe (23-24 Nis):** Rehber deneyimi
- [ ] `prepare_counsellor_brief(soz_no)` tool — 1 gün
- [ ] Ret → yönlendirme refleksi (SYSTEM_PROMPT kuralı) — 2 saat

**Cuma (25 Nis):** Öğretmen değeri
- [ ] `get_class_brief(sinif, ders, tarih)` tool — 1 gün
- [ ] Öğretmen dashboard UI (mevcut dashboard'a ek kart) — yarım gün

**Hafta sonu (26-27 Nis):** Test + rapor
- [ ] Tüm değişiklikler regresyon testi
- [ ] Neo + Duygu canlı kullanım denemesi

---

### Hafta 2 (28 Nis - 4 May) — Pedagojik Derinlik

**Pazartesi-Salı:** Transfer failure + adaptive re-explain
- [ ] `analyze_transfer_gap(soz_no)` — topic_tracker × student_exams cross
- [ ] SYSTEM_PROMPT'a "farklı yaklaşım" kuralı (analoji/formül/örnek rotasyonu)

**Çarşamba-Perşembe:** Veri iyileştirme
- [ ] Derslik D-1 bug fix (Eyotek'ten gerçek derslik bilgisi çek)
- [ ] [AYT] prefix sahte kayıtları temizle
- [ ] `sinav_hata_yuzdesi` → `sinav_basari_yuzdesi` rename (kolon adı yanlış)

**Cuma:** Tercih listesi
- [ ] `otomatik_tercih_listesi(soz_no, tercihler_sayisi=24)` tool
- [ ] YÖK Atlas + puan tahmin + burs filtresi kombinasyonu

---

### Hafta 3-4 (5-18 May) — Veli + Yaz Kampı Hazırlığı

**Hafta 3:** Veli modülü template
- [ ] Haftalık digest mesaj şablonu (net trendi + devamsızlık + öne çıkan konu)
- [ ] Pazar 20:00 scheduler (OUTREACH_ENABLED=false hala — sadece draft)
- [ ] 5 veli pilot için test (Neo manuel gözden geçirsin)

**Hafta 4:** Yaz kampı UI
- [ ] Günlük self-report ekranı (web chat'te 5 soru)
- [ ] Kamp üye yönetimi (admin tab'a ekle)
- [ ] Haftalık progress raporu template

---

### Hafta 5-8 (19 May - 15 Haz) — Muhasebe İnşa + Optimization

**Neo + Duygu paralel:**
- [ ] Muhasebe şema (memory/project_muhasebe_guvenlik.md plan)
- [ ] Eyotek muhasebe sayfalarından Excel export
- [ ] SQL AST guard muhasebe tablo blacklist
- [ ] Test ortamında CRUD

**Optimization (arka plan):**
- [ ] Tool call cache (5dk TTL per student)
- [ ] Uzun çıktı 1800 char eşik otomatik web link
- [ ] Whisper ses pipeline (OpenAI key aktif)
- [ ] `generate_concept_diagram` tool (Claude Vision ile)

---

### Haziran — Yeni Sezon Son Hazırlık

- [ ] Yaz kampı pilot (Temmuz 28 — 40 öğrenci)
- [ ] Öğretmen onboarding pilot (3 öğretmen seç)
- [ ] Deployment guide simülasyon
- [ ] Outreach worker scripti (approved → send)

---

### Temmuz-Eylül — Lansman

- **Temmuz 28:** Yaz kampı başlar, `YAZ_KAMPI_ACTIVE=true`
- **Ağustos:** Veli pilot (5 veli), muhasebe canlı (Duygu)
- **1 Eylül:** Tüm flag açılır (`OUTREACH_ENABLED`, `VELI_MODULE_ACTIVE`, `ALERTS_ACTIVE`)
- **Eylül-Ekim:** 30 gün yoğun monitoring

---

## 📊 Önem × Efor Matrisi

```
YÜKSEK ETKİ
     │
     │  [Plan State]           [Veli Digest]
     │  [Data Audit]           [Öğretmen Brief]
     │  [Frustration Route]    [Transfer Gap]
     │
     │  [Adaptive Re-explain]  [Muhasebe Modülü]
     │  [Tool Cache]           [Whisper Pipeline]
     │
     │  [Tercih Listesi]
     │  [Concept Diagram]
     │
DÜŞÜK ETKİ
     └─────────────────────────────────────── EFOR
       KOLAY                          ZOR
```

**İlk 2 hafta odak:** sol üst (yüksek etki + kolay) — Plan State, Data Audit, Frustration Route.

---

## 🎯 Başarı Metrikleri (5 hafta sonra değerlendir)

| Metrik | Bugün | Hedef 25 Mayıs |
|--------|-------|----------------|
| Claude ortalama latency | 20s | 12s (cache + state) |
| Öğrenci frustration sinyali/hafta | 3-5 | <2 |
| Plan güncelleme süresi | 25-40s | 3-5s |
| Öğretmen aktif kullanım | 0 | 3/12 |
| Rehber haftalık rapor yazma | Manuel 30s | Tool 5s |
| Kirli veri (NULL/prefix) | ~100 kayıt | <10 |

---

**🔑 Kritik Nokta:** Bu 20 bulgunun 17'si bot'un kendi içeriden görüşünden çıktı. Yani sistem **kendini nasıl geliştireceğini biliyor** — biz sadece onun gördüğünü kod haline getiriyoruz. Atlas self-observing mimarimiz meyvesini veriyor.
