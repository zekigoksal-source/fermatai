# FermatAI — Sistem Durum Raporu ve Yol Haritası

**Tarih:** 19 Nisan 2026
**Rapor Hazırlayan:** Claude (mimari tarama: mühendislik + güvenlik + kalite + verimlilik bakış açısı)
**Kapsam:** Tüm eyotek_agent/ modülleri (96 .py dosya), SYSTEM_PROMPT, DB yapısı, routing, ACL, RAG

---

## 🟢 BUGÜN CANLIYA HAZIR — 3 KRİTİK FIX UYGULANDI

### Fix #1 — SQL Injection (KRİTİK)
- **Dosya:** `fast_responses.py:839`
- **Sorun:** `f-string` ile pattern SQL'e gömülüyordu. Escape sadece `'` içindi, `%` ve yorum enjeksiyonu mümkün olabilirdi.
- **Exploit:** Kullanıcı "Ali'; DROP TABLE x; --" dese koruma delinebilirdi.
- **Fix:** `$1` parametreli sorgu. Artık asyncpg driver özel karakterleri güvenli handle ediyor.

### Fix #2 — Intent Parser None Crash (KRİTİK — 157 kez/24h)
- **Dosya:** `whatsapp_bridge.py:2246`
- **Sorun:** `intent` None döndüğünde `if not intent: pass` + sonrasında `intent.entities` erişimi → AttributeError.
- **Etki:** 157 mesaj son 24 saatte intent analizi başarısız, bot fallback'e düştü ama crash log oluştu.
- **Fix:** None durumda `SimpleNamespace(action_type='UNKNOWN', entities={})` dummy intent. Devam eden entity processing güvenle çalışıyor.

### Fix #3 — Date toordinal (KRİTİK — 11 kez/24h)
- **Dosya:** `web_chat.py:738`
- **Sorun:** `$2::date` cast'i string parametresini date objesine çeviremiyor, asyncpg serialization hatası.
- **Etki:** Web chat "History Day" endpoint çöküyordu — geçmiş sohbetler yüklenmiyordu.
- **Fix:** Python tarafında `date.fromisoformat(gun)` ile date objesi üretip parametre olarak geç.

**Bu 3 fix'in tek başına katkısı:** Production stabilite +168 hata/gün azalır. Bridge restart sonrası aktif.

---

## 📊 SİSTEMİN GENEL FOTOĞRAFI

### Mimari Katmanlar (7 seviye)
```
1. WhatsApp/Web kullanıcı mesajı
2. FastAPI Bridge (whatsapp_bridge.py port 8001, web_chat.py)
3. Kimlik + ACL kontrolü (_get_caller_profile, role matrix)
4. Routing karar noktası (üç yerde — çakışma var, bkz #1)
5. LLM katmanı (fast_responses %50 → Ollama %20 → Claude %30)
6. Tool calling (17 tool, Claude dispatcher)
7. Veri katmanı (PostgreSQL + Eyotek Playwright CDP)
```

### Rakamsal Durum (19 Nisan itibarıyla)
| Metrik | Değer |
|--------|-------|
| Öğrenci sayısı | 125 (students tablosu) |
| Personel sayısı | 18 (staff) |
| RAG içerik | 4,482 kayıt (36 konu + 4,092 OGM + 390 Vision) |
| Universite taban DB | **35,584 kayıt** (4 yıllık, 4 puan türü) |
| Sınav analizi | 107/125 öğrenci |
| Etüt geçmişi | 2,421 kayıt |
| Atlas suggestion | Lifecycle aktif (new/recurrence/regression) |
| Token tasarrufu (C15) | Admin/Müdür -37%, Öğrenci -9% |
| Query cache | bge-m3 semantic, exact hash + semantic 0.80 |

### Routing Dağılımı (hedef vs gerçek)
- Fast Response: **%50** (hedef) — şu an ~%39-50 arası
- Ollama: **%20** (hedef)
- Claude API: **%30** (hedef)

### Aktif Güvenlik Katmanları
1. ✅ Telefon = kimlik + ACL matrix
2. ✅ SQL ACL guard (`_check_sql_acl`) — role bazlı tablo/kolon filtresi + OR/UNION regex block
3. ✅ Fast response ACL (başka öğrenci adı)
4. ✅ LLM prompt ACL (system prompt kuralları)
5. ✅ Bilinmeyen numara engeli
6. ✅ Flood koruma (30+ mesaj/dk → 1 saat ban)
7. ✅ Hack defense (5+ jailbreak → fizik sorusu)
8. ✅ get_atlas_trend çift katman (role=admin + phone=Neo)

---

## 🟡 ORTA VADELİ ÖNERİLER (1-2 hafta)

### A) Mimari Sadelik — Çift Routing Karar Noktasını Birleştir
**Tespit:** 3 yerde routing kararı alınıyor:
- `whatsapp_bridge.py:2138` → `try_fast_response()`
- `routing_engine.py:25` → `decide_route()`
- `llm_router.py:40` → `classify_complexity()`

**Risk:** Cache düşüklüğü, bakım yükü, davranış tahmin edilmez oluyor.

**Plan:** `routing_engine.decide_route()` tek kaynak. `llm_router` deprecated. Bridge sadece enforcer. **Tahmin: 3-4 saat.**

### B) DB Pool Konsolidasyonu — 8 modülde _pool → db_pool
**Tespit:** KALDIGIM'de "Oturum 21 borcu" olarak kaydedilmiş, hala aktif:
- `admin_dashboard._dash_pool`, `analytics_cache._pool`, `conversation_memory._pool`, `fast_responses._pool`, `rag_engine._pool`, `study_plan_builder._pool`, `usage_tracker._pool`
- Her biri kendi pool'u yaratıyor → Postgres'e 20-30 idle bağlantı, connection leak riski.

**Plan:** Hepsini `db_pool.get_pool()`'a migrate. Tek pool, min=2, max=10. **Tahmin: 1-2 saat.**

### C) Türkçe Karakter Utility Birleştirme
**Tespit:** Aynı `_tr_lower/upper/title` fonksiyonu 3 dosyada:
- `fast_responses.py:27-40`
- `conversation_viewer.py:110-115`
- `fermat_core_agent.py:4154-4156`

**Risk:** Bug fix (ör. İ/I handling) sadece birinde yapılırsa diğerleri stale.

**Plan:** `utils/turkish.py` merkez modül. **Tahmin: 30 dk.**

### D) Fast Response Pattern Önceliklendirme
**Tespit:** `fast_responses.py` OGRENCI_PATTERNS içinde "selam" ve "sohbet" örtüşüyor. İlk yakalanan wins.

**Plan:** Priority-ordered dict'e çevir, çakışmaları regex exclusion ile çöz. **Tahmin: 1 saat.**

### E) Halusinasyon Direnci — sinav_hata_yuzdesi Anlam Ters-Düz
**Tespit:** Kolon adı "hata_yuzdesi" ama gerçekte "başarı yüzdesi":
- Bazı sorgularda ASC (düşük = zayıf) kullanılıyor
- Bazı sorgularda DESC (yüksek = zayıf) kullanılıyor
- Claude bu tutarsızlıkta yanlış yorum yapabiliyor.

**Plan:** Migration — `sinav_basari_yuzdesi` VIEW veya generated column ekle (`100 - sinav_hata_yuzdesi`). Tüm sorgular yeni kolona çevrilir. **Tahmin: 1 saat + migration test.**

---

## 🔴 KRİTİK — PLANLANMASI GEREKEN UZUN VADELİ İŞLER (2-4 hafta)

### 1. Claude Raw SQL Execution — Parameterize veya AST Validate
**Risk:** `query_analytics` tool'u Claude'un ürettiği SQL'i `await conn.fetch(sql)` ile execute ediyor. `_check_sql_acl` regex'i güçlü ama AST seviyesinde değil.

**Potansiyel exploit:** Prompt injection + regex bypass kombinasyonu → başka öğrenci verisi sızdırma.

**Plan:**
- Opsiyon A: Tool'u `query_student_data(soz_no, domain)` gibi yapılandırılmış forma dönüştür (Claude SQL yazmıyor, parametre veriyor).
- Opsiyon B: SQL'i `sqlglot` AST parse + whitelist validation.
- **Tahmin: 1-2 hafta**, test yoğun.

### 2. Prompt Injection / Jailbreak Defense Güçlendir
**Risk:** Mevcut defense sadece 1 kez fizik sorusu fırlatıyor. Öğrenci 5+ kez dense, savunma tükenir.

**Plan:**
- Per-session jailbreak counter + 30dk lock-out
- "system/prompt/admin/rule" keyword throttle
- **Tahmin: 2-3 saat**, gerçek konuşma örneklerinde test

### 3. OTP Replay + SameSite Strict
**Risk:** `verify_otp()` sonrası `otp_used_at` update yok → aynı OTP 2 kez kullanılabilir. SameSite=Lax CSRF'e açık.

**Plan:**
- OTP kullanım işaretleme
- Cookie SameSite=Strict, Token TTL 30dk
- **Tahmin: 1-2 saat**

### 4. Sensitive Data Logging Filter
**Risk:** `logger.debug(f"params: {params}")` tool parametrelerini logluyor (note içeriği, student_id, öğretmen adı). Log dosyaları sysadmin erişiminde.

**Plan:**
- Logger middleware: phone, email, TC, note_content, message_text → `***`
- **Tahmin: 1 saat**

### 5. Backup / Recovery
**Risk:** PostgreSQL backup yok. Kazara `DELETE/DROP` durumunda recovery imkanı yok.

**Plan:**
- `pg_dump` cron (günde 2x)
- S3 replication
- Aylık recovery test
- **Tahmin: 2-3 saat kurulum + dokümantasyon**

---

## 🟢 MEVCUT KABİLİYETLERLE YENİ FIRSATLAR

### Veri zenginliği artık zengin cevap üretebilir
1. **YÖK Atlas 35,584 kayıt** → öğrenci "bu puanla hangi bölüm" dediğinde 4 yıllık trend + taban + sıralama göster. Şu anki tool (`ogrenci_nereye_girebilir`) bu veriyi daha agresif kullanabilir.

2. **Query cache bge-m3** → öğrenci aynı konuyu farklı kelimelerle sorduğunda 50ms'de döner. Kavramsal cache hit rate'i arttırmak için Claude cevaplarının sonuna "_italik_ kapanış sorusu" zorunluluğu mevcut → bu cache-friendly.

3. **Atlas self-observing** → bot kendi hatalarını görüyor (signature + occurrence). Neo "atlas trend" komutu ile son 30 günde hangi kategoride kaç sorun çıktı görür. Regresyon tespiti otomatik.

4. **Rol-aware prompt (-%37)** → admin/mudur/ogretmen cevapları artık daha hızlı, daha ucuz. Cache hit rate +%15-20 tahmin.

### Hazır cevaplara yeni derinlik eklenebilir
- Öğrenci "netim nasıl" dediğinde → şu an fast response versiyon + Claude analitik. Fast response'a son 3 deneme trendi + YÖK Atlas'tan mevcut puanla hedeflenebilir bölümler ekle.
- "Hangi bolume gidersem" → fast response (puana göre direkt DB sorgu) + Claude pedagojik yorum. Claude'a tool çağırmasına gerek kalmadan hazır veri.

---

## 🎯 ÖNCELİKLENDİRME (Etki/Maliyet Matrisi)

| İş | Etki | Maliyet | Öncelik |
|----|------|---------|---------|
| ✅ 3 kritik fix (bugün) | Çok Yüksek | Düşük | **YAPILDI** |
| DB pool konsolidasyonu | Yüksek | Düşük | **HAFTA 1** |
| Türkçe utility birleştirme | Düşük | Çok Düşük | HAFTA 1 |
| Routing merkezleştirme | Orta | Orta | HAFTA 2 |
| Prompt injection defense | Yüksek | Düşük | HAFTA 2 |
| OTP replay + SameSite | Orta | Düşük | HAFTA 2 |
| Sensitive data logging | Orta | Düşük | HAFTA 2 |
| SQL execution refactor | **Çok Yüksek** | Yüksek | HAFTA 3-4 |
| PostgreSQL backup | Çok Yüksek | Orta | HAFTA 1 (ASAP) |
| sinav_hata_yuzdesi migration | Orta | Düşük | HAFTA 1 |

---

## 📈 SELF-AWARENESS GELIŞİMİ — YAPABILECEKLERIMIZ

Sistem kendi durumunu giderek daha iyi tanıyor:
- ✅ Atlas lifecycle (yeni/tekrar/regresyon)
- ✅ Query cache istatistik (hit rate)
- ✅ Deployment tracking (her restart'ta kayıt)
- ✅ Routing stats (her mesaj kaynak + süre)
- ✅ Self-observer (kalite değerlendirmesi)

**Eklenebilir:**
1. **Tool çağrı başarı oranı** — `tool_call_stats` tablo: hangi tool ne kadar kullanılıyor, başarı/hata oranı, ortalama süre.
2. **Prompt cache hit/miss metric** — Claude cevap header'ından cache hit oranı oku, loga kaydet.
3. **Halusinasyon tetikleyici pattern tespiti** — `self_observer.log_quality` sonuçlarını kategorize et, "yanlış cevap olası" sorguları işaretle.

---

## 🛡️ VERİ KAYBI RİSKİ — MEVCUT DURUM

- PostgreSQL backup: **YOK** (kritik)
- Git commit sıklığı: Belirsiz (manuel, Neo kontrolünde)
- Log rotation: loguru 20MB/14gün — TAMAM
- `execute_eyotek_action` default dry_run: TAMAM (çift koruma)
- Kullanıcı onayı gerektiren yazma: TAMAM

**Öneri:** Sadece günde 1 kez `pg_dump` komutu cron — `backups/fermatai_YYYYMMDD.sql`. Disk alanı problem değil (student sayısı 125).

---

## 📝 BU OTURUMDA UYGULANAN DEĞİŞİKLİK ÖZETİ

1. **Token bilinci kalıcı kuralı** → `feedback_token_bilinci.md`
2. **Kapsamlı sistem taraması** → 3 paralel agent
3. **SQL injection fix** → `fast_responses.py:839`
4. **Intent None crash fix** → `whatsapp_bridge.py:2246`
5. **toordinal fix** → `web_chat.py:738`
6. **Syntax/import testler** → tümü PASS

Bridge restart sonrası bu 3 fix canlıya çıkar. Diğer yol haritası maddeleri ayrı oturumlarda ele alınacak — her biri önce Neo onayına sunulacak, sıkıştırılmış koda geçilecek, A/B test ile regresyon kontrolü yapılacak.

---

**Rapor Sonu.** Bu doküman gelecek oturumlarda "sistem durumu referansı" olarak kullanılabilir. Her büyük değişiklik sonrası bu tablolar güncellensin.
