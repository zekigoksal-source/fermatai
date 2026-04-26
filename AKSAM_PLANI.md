# 🌙 Akşam İçin Yapılacaklar Planı

> **Hazırlanma:** 26 Nisan 2026, öğleden sonra
> **Son commit:** `a10bea2` (cohort NET ortalama fix — Neo halüsilasyon yakaladı)
> **Backup tag:** `oturum-25-14h-stable`
> **Sistem durumu:** ✅ Stabil — bridge active, 4/4 endpoint 200, 3 timer kurulu
>
> Akşam bilgisayar başına gelince bu listeyi sırayla geç. Her madde için
> tahmini süre + risk + ön koşul belirtildi.

---

## ✅ ÖĞLEDEN SONRA YAPILANLAR (26 Nisan, oturum 25.14g+h)

| İş | Sonuç |
|---|---|
| Çalışmam butonu same-tab fix | `window.location.href` (oturum 25.14b) |
| Admin "📊 Yönetim Paneli" butonu chat header | Same-tab, admin only |
| Cohort tab boş görünüm fix (71 → 123 öğrenci) | mezun + sınıfsız + small classes dahil |
| **Cohort AYT 67 net halüsilasyon fix** | NET ortalama (puan değil), TYT `/120`, AYT `/80` ayrıştırıldı |
| Conversation viewer Cinema palette revize | Glassmorphism + Fira fonts |
| Backup tag | `oturum-25-14h-stable` |

**Halüsilasyonun kökü:** `student_exams.toplam[exam_type='AYT']` aslında TG (Tam Gün, TYT+AYT birleşik) içeriyor. Düzeltme: `student_exam_analysis.ders_netleri_ayt` JSONB'den pure AYT ayrıştırıldı.

**Yeni cohort verisi (canlı doğrulandı):**
- Mezun SAY: 27 öğr, TYT 70 net, **AYT 15.5 net** (eskiden 67 = imkansız)
- 12 SAY: 19 öğr, TYT 61.5, AYT 18
- Mezun EA: 7 öğr, TYT 40.4, AYT 26.4

---

## 🎯 ÖNCELİK 1 — Kullanıcı Deneyimi Test (~20 dk, RİSK SIFIR)

### Çalışmam paneli gerçek öğrenci ile dene
- [ ] Web chat'e öğrenci olarak gir (bilinen telefon)
- [ ] "📚 Çalışmam" tıkla → aynı sekmede açılıyor mu?
- [ ] 1-2 program ekle, 1 todo, 1 alışkanlık (paragraf çözümü)
- [ ] 30dk Matematik + 10 soru log et
- [ ] Mood "verimli" seç + 1 not yaz
- [ ] "← Sohbete Dön" → aynı sekme, history kaybolmuş mu?
- [ ] Bot'a "bana plan yap" yaz → daily_brief okuyup proaktif cevap mı veriyor?
- [ ] Analizim section: doughnut/timeline/heatmap dolmaya başlıyor mu?

**Kanıt göster:** 2-3 ekran görüntüsü Neo'nun WP'sine veya buradaki sohbete

---

## 🎯 ÖNCELİK 2 — Admin Dashboard Premium Revize (~45 dk, RİSK DÜŞÜK)

`eyotek_agent/dashboard_ui.html` şu an basit, mevcut Cinema palette uygula:
- 8 tab (Genel, Bildirimler, Routing, Sınıflar, Öğretmenler, Maliyet, Atlas-2, Öğrenci)
- Glassmorphism + animated blobs
- Fira fonts (mono data, sans body)
- Premium chart styling (gradient fill, dark tooltip)
- Tab geçişleri smooth

**Öncesinde:** ui-ux-pro-max'tan "admin panel" + "data dashboard" sorgu çek
```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "admin panel dashboard" --domain product
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "data dense analytics" --domain style
```

**RİSK:** Düşük — sadece CSS, JS+layout aynı. Mevcut dashboard çalışıyor, regression yok.

---

## 🎯 ÖNCELİK 3 — LLM Bot Proaktif Test (~30 dk, RİSK SIFIR)

Daily_brief context'i gerçekten bot davranışına yansıyor mu?

**Test senaryoları (öğrenci olarak chat'te):**
1. **Önce:** Çalışmam'da 30dk Matematik + 10 soru ekle
2. Sohbete dön, **"plan yap"** yaz → Bot "bugün 30dk Mat çalıştın" demeli
3. **"yarın için ne çalışayım"** → Bot Mat devamı/Limit önermeli
4. **Mood "yorgun" iken:** "yoğun program ver" → Bot HAFİF plan vermeli
5. **2 boş gün geçirdikten sonra:** Plan iste → Bot empati göstermeli ("yardım edeyim mi")

**Kanıt:** Konuşmaları DB'den çek, daily_brief context'in hangi mesajlara yansıdığını gör.

---

## 🛠️ ÖNCELİK 4 — Çalışmam Panelinden Bot'a Aksiyon (~60 dk, RİSK ORTA)

Şu an bot SADECE okuyor. Yazma da yapsın:
- Bot "16:00 Matematik ekleyeyim mi?" der → Öğrenci "evet" → Bot **gerçekten programa ekler**
- Yeni Claude tool: `add_to_student_program`

**Yapılacak:**
1. `tool_definitions.py` → yeni tool: `add_to_student_program(soz_no, title, time, ders)`
2. `fermat_core_agent.py` → wrapper `_tool_add_to_student_program` (student_daily.add_daily_program çağırır)
3. ACL: sadece **kendi soz_no'su için** (admin override)
4. Test: chat'te "evet ekle" → DB'de görünüyor mu?
5. UI: Çalışmam refresh edince yeni blok görünüyor mu?

**RİSK:** Orta — yazma aksiyonu, ACL kritik. Test öğrenci ile dene önce.

---

## 🎓 ÖNCELİK 5 — ELO + Knowledge Graph Aktif Kullanım (~40 dk, RİSK DÜŞÜK)

`adaptive_engine` ve `knowledge_graph` modülleri var ama hiç kullanılmıyor. Aktive et:

### Foto soru çözüm sonrası ELO update
- Öğrenci foto soru gönderir → bot Vision ile çözer → **`observe_student_answer` çağrılır**
- Doğru/yanlış + ders/konu Vision'dan çıkarılır
- ELO + SM-2 + misconception otomatik güncellenir

**Yapılacak:**
1. `whatsapp_bridge.py` foto handler — Vision yanıt sonrası `observe_student_answer` çağır
2. Vision prompt'a "ders + konu + doğru/yanlış extract" talimatı ekle (zaten var olabilir)
3. Test: Test fotoğrafı ile akış dene, DB'de `student_topic_elo` satırı oluştu mu?

**Bağlı kazanım:** 4-5 ay sonra her öğrencinin ELO mastery haritası → Çalışmam Analizim section "ELO top 5" gerçek veri ile dolar.

---

## 📚 ÖNCELİK 6 — Atlas-2 İlk Önerileri İncele (~15 dk, NEO DEV İŞİ)

Yarın 02:00'da Atlas-2 cron çalışacak. Sabah:
1. `/admin/dashboard?token=...` → Atlas-2 sekmesi
2. Bot'un kendi prompt'una önerdikleri öneriler ne?
3. Mantıklı 1-2 öneri varsa **approve + apply** (Neo manuel onay)
4. Saçma olanları reject et

---

## 🟢 ÖNCELİK 7 — REFACTOR_PLAN P1.2 (~30 dk, RİSK ORTA)

System prompt cleanup — eski oturum yorumlarını temizle:
- `system_prompts.py` ~1430 satır
- Eski Oturum 18-22 yorumları (#) sil
- Logic kuralları KORU (yorum dışında her şey aynı)
- Token tasarruf ~500 tok

**RİSK:** Bir satır kural yanlışlıkla silinirse bot davranışı değişir. **MANUEL review** zorunlu — her diff'i göz at.

---

## ❌ YAPMA — Olgun Sistemleri Bozma

Neo emri (26 Nisan): "Conversation viewer = web chat ise dokunma, çok olgun."

**DOKUNULMAYACAKLAR:**
- ❌ `web_chat_ui.html` — öğrenci sohbet ekranı (beğeniliyor)
- ❌ `conversation_viewer.py` — admin liste viewer (basit ama fonksiyonel)
- ❌ `whatsapp_bridge.py` ana akış (4215 satır, çok riskli)
- ❌ `fermat_core_agent.py` ana akış (4150 satır, çok riskli)
- ❌ `fast_responses.py` modülerleştirme (3289 satır, regression riski)

**P2.x büyük refactor'ler REFACTOR_PLAN.md'de bekliyor** — sen onay verince yapılır, test coverage 200+ olduktan sonra.

---

## 🔎 ÖĞLEDEN SONRA NET KONTROL EDİLMESİ GEREKEN (akşam P1.5)

Cohort'ta puan → net düzeltmesini yaptım. **Diğer admin tab'larında da benzer halüsilasyon riski var mı?** Akşam ilk iş bunu kontrol et:

- [ ] **Routing tab** — sayılar tutarlı mı? (claude/groq/fast oranı)
- [ ] **Bildirimler tab** — son 7 gün doğru gösteriyor mu?
- [ ] **Öğretmenler tab** — etüt sayıları, ortalama süreler doğru mu?
- [ ] **Maliyet tab** — günlük token/dolar tahmini gerçeğe yakın mı?
- [ ] **Atlas-2 tab** — sabah cron çalıştıysa öneri var mı?
- [ ] **Öğrenci detay tab** — bir öğrenciye tıkla, AYT/TYT verisi doğru mu?

**Yöntem:** Her tab için DB'den ham veri çek, ekrandaki rakamla karşılaştır. Tutmuyorsa SQL'i araştır.

---

## 📊 Sistem Sağlık Snapshot (akşam başlamadan önce kontrol)

```bash
ssh -i C:/Users/zekig/.ssh/id_ed25519_fermatai neo@116.203.117.106 \
  "systemctl is-active fermatai-bridge && \
   systemctl list-timers --all | grep fermatai | head -5 && \
   docker exec fermat_postgres psql -U fermat -d fermatai -c \
     'SELECT response_source, COUNT(*) FROM routing_stats WHERE created_at >= NOW() - INTERVAL \'1 day\' GROUP BY response_source'"
```

Beklenen:
- `active`
- 3 timer (backup 03:00, eyotek-daily 04:00, smart-sync Mon/Thu 04:30)
- Routing dağılımı: claude/groq/fast karışım

---

## 🎯 Önerilen Sıra (toplam ~3.5 saat akşam)

```
1. 🟢 P1 UX test (20dk)               → Eldeki ürünü tanı
2. 🟡 P3 LLM proaktif test (30dk)     → Bot'un veriyi okuduğunu kanıtla
3. 🟡 P5 ELO foto entegrasyon (40dk)  → Yeni veri kanalı aç
4. 🟠 P4 Bot programa yazma (60dk)    → Çift yönlü akış
5. 🟢 P2 Admin dashboard premium (45dk) → Görsel oturma
6. 🔴 P7 System prompt cleanup (30dk) → Token tasarruf (manuel)
7. 🟢 P6 Atlas-2 inceleme (15dk)      → Sabaha kalır da, akşam değerlendir
```

---

## 🔗 Hızlı URL'ler

| Görev | URL |
|-------|-----|
| Web chat | `https://api.fermategitimkurumlari.com/chat?token=fermat_agent_secret_2026` |
| Çalışmam panel | `https://api.fermategitimkurumlari.com/student/daily/dashboard?token=fermat_agent_secret_2026` |
| Admin dashboard | `https://api.fermategitimkurumlari.com/admin/dashboard?token=fermat_agent_secret_2026` |
| Konuşma viewer | `https://api.fermategitimkurumlari.com/chat/admin/conversations?token=fermat_agent_secret_2026` |
| Atlas-2 önerileri | `https://api.fermategitimkurumlari.com/admin/dashboard?token=...` → Atlas-2 sekmesi |

---

## 🛡️ Güvenlik Hatırlatıcı (her oturum başı kontrol)

1. ✅ VPS git senkron (`git log -1` local + VPS aynı commit)
2. ✅ Test'ler PASS (`pytest tests/test_*.py`)
3. ✅ Endpoint'ler 200 (chat + dashboard + student daily)
4. ✅ Eyotek session online
5. ✅ CapSolver bakiye > $1
6. ✅ Hiçbir şey yapmadan ÖNCE: backup tag at (`git tag oturum-25-X-stable`)

---

## 📝 Akşam Sonrası KALDIGIM Update Şablonu

```markdown
## 🆕 OTURUM 25.15 (akşam tarihi) — [Konu]

### Neo'nun talebi
> [...]

### Yapılan
- ...

### Test sonuçları
- pytest: X/X PASS
- canlı E2E: ...

### Commit
- hash — kısa açıklama
```

İyi akşamlar Neo. Sabah görüşürüz. 🌙
