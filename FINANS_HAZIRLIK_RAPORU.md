# 🔐 FermatAI — Finans Modülü Hazırlık Raporu (22.1n-neo)

**Tarih**: 20 Nisan 2026, 22:00
**Durum**: ✅ Altyapı HAZIR, Neo verilerini beklemekte

---

## 🎯 Neo Talimatı

> "Sadece ben ulaşıyor olacağım. Öğrenci bile veli bile kendi finansal borç kaydına giremez.
> Sistemde sadece benim ulaşabileceğim bir katman olacak — şirketin finansal durumunu
> tartışıp strateji oluşturacağım."

## ✅ Kurulan Güvenlik Katmanları (7 katman derinliğinde savunma)

### 1. **Kişi-Bazlı Authorization** (`finans_access.is_finans_authorized`)
- Sadece `NEO_PHONE` (905051256802) True döner
- Rol "admin" olsa bile — farklı phone → REDDET
- SGM (Orsel), Duygu, Mahsum, tüm müdürler — DAHİL REDDEDİLİR

### 2. **SQL Guard** (`role_access._check_sql_acl` + `finans_access.check_finans_sql_access`)
- Her SQL sorgusu finans tablosu/kolonu kontrolünden geçer
- Finans içerik tespitinde phone != Neo → hata mesajı + audit
- Admin/mudur SQL ACL atlama — finans için DEVRE DIŞI (en önemli bug fix)

### 3. **Tool ACL** (`role_access._ACL_MATRIX`)
- 6 finans tool'u SADECE admin ACL'sinde
- Diğer 8 rolde (mudur, yonetim, ogretmen, rehber, ogrenci, veli, guest, unknown) **YOK**
- `run_tool` dispatcher'da ekstra phone check — admin rolü + Neo phone zorunlu

### 4. **Vision API Guard** (`whatsapp_bridge.py` photo handler)
- Caption'da finans keyword (borç, taksit, ödeme, tutar, maaş, makbuz, TL, TRY) varsa
  Vision API çağrılmaz — Anthropic sunucusuna base64 screenshot gitmez
- Neo bile finans SS atsa → "manuel gir" yanıtı

### 5. **Cache Deny** (`scrape_cache` + `analytics_cache`)
- `finans_*`, `payment_*`, `borc_*`, `taksit_*`, `tahsilat_*` prefix'li operation'lar
  cache'e yazılmaz, okunmaz (plaintext disk sızıntı riski)
- Her çağrıda DB'den fresh read

### 6. **Ollama Redirect** (`llm_router._PERSONAL_KEYWORDS`)
- Finans keyword varsa routing **cloud** (Claude + tool_call)
- Ollama system prompt'ta kesin yasak: finans verisi uydurma, tahmin, veri üretme
- Hassas rakam asla yerel modele gitmez

### 7. **Audit Log** (`financial_audit_log` DB tablosu + triggers)
- Her finans erişimi (başarılı/bloklanan) kaydedilir
- DB trigger: `monthly_installments` ve `payments` tablolarında INSERT/UPDATE/DELETE her hareket
- Neo raporu: `finans_audit_rapor(saat=24)` — olağandışı erişim tespit

## 📋 Oluşturulan Dosyalar

### Modüller
| Dosya | İşlev |
|-------|-------|
| `finans_access.py` | Güvenlik katmanı: authorization, SQL guard, Vision/Cache filter, audit |
| `finans_tools.py` | 6 Claude tool fonksiyonu (is_finans_authorized guard per-tool) |
| `schema/finans_schema.sql` | DB schema: 5 tablo + 3 view + triggers |
| `tests/test_finans_security.py` | 30 güvenlik testi (kritik regresyon koruması) |

### Entegrasyon
| Dosya | Değişiklik |
|-------|-----------|
| `role_access.py` | `_check_sql_acl` phone parametresi + finans guard çağrısı |
| `fermat_core_agent.py` | `tool_query_analytics` finans audit, run_tool finans dispatch |
| `tool_definitions.py` | 6 finans tool schema eklendi (31 → 37 tool) |
| `whatsapp_bridge.py` | Vision endpoint'e finans caption filter |
| `llm_router.py` | `_PERSONAL_KEYWORDS` finans keyword'leri + Ollama prompt yasak |
| `scrape_cache.py` | `set_cache`/`get_cached` finans deny |

## 🗄️ DB Schema

### Tablolar
- **`financial_audit_log`** — her finans erişim log (append-only)
- **`monthly_installments`** — aylık taksitler (soz_no, ay, yıl, vade, tutar, ödenen_mi)
- **`payments`** — yapılan ödemeler (nakit/havale/kart, makbuz, installment FK)
- **`veli_iletisim`** — veli bilgilendirme kayıt (draft/onaylandı/gönderildi)
- **`kurum_gelir`** — kurumsal gelir/gider (manuel giriş, kategori bazlı)

### View'lar (materialize-like, live-compute)
- **`student_financial_summary`** — öğrenci bazlı özet (kalan borç, geciken, toplam)
- **`geciken_taksit_ozet`** — sadece gecikenler
- **`monthly_revenue_summary`** — son 12 ay tahsilat kırılımı

### Triggers
- `trg_inst_updated` — `monthly_installments.updated_at` otomatik
- `trg_inst_audit`, `trg_pay_audit` — INSERT/UPDATE/DELETE audit log

## 🔧 Claude Tool'ları (6 adet)

| Tool | Kullanım | Audit |
|------|----------|-------|
| `finans_ozet` | Kurum geneli: toplam borç, tahsilat, geciken, borçlu öğrenci sayısı | ✅ |
| `ogrenci_borc_detay` | Tek öğrenci: taksit listesi + ödeme geçmişi | ✅ |
| `geciken_odemeler` | N günden fazla geciken (sıralı, max 500) | ✅ |
| `aylik_tahsilat_trend` | Son N ay tahsilat kırılımı (grafik için) | ✅ |
| `veli_borc_bildirim_taslak` | Veli mesaj TASLAK (gönderilmez, draft DB'ye) | ✅ |
| `finans_audit_rapor` | Son N saat finans erişim audit | ✅ |

**Her tool içinde**:
1. `is_finans_authorized(phone)` → Neo değilse ret + audit
2. `check_finans_rate_limit(phone)` → günlük max 200 sorgu
3. `log_finans_access(...)` → her erişim (başarılı/başarısız) kayıt
4. Decimal → float, date → ISO serialization

## 🧪 Test Sonuçları

```
tests/test_fast_response_core.py    12/12 ✅
tests/test_ayt.py                    9/9 ✅
tests/test_registry.py              49/49 ✅
tests/test_security.py              15/15 ✅
tests/test_phone_utils.py           18/18 ✅
tests/test_oturum20.py              18/18 ✅
tests/test_finans_security.py       30/30 ✅  ← YENİ
──────────────────────────────────────────────
TOPLAM                             151/151 ✅
```

## 🔍 Saldırı Senaryoları — Test Edildi

| Senaryo | Savunma | Test |
|---------|---------|------|
| SGM (Orsel) admin rolü ataması alıp finans sorguluyor | phone ≠ Neo → SQL guard bloklar | ✅ `test_sql_admin_role_sgm_blocked` |
| Müdür Duygu `SELECT * FROM payments` | Rol admin değil + phone ≠ Neo → bloklu | ✅ `test_sql_mudur_duygu_blocked` |
| Öğrenci `SELECT taksit_tutari FROM ...` | Rol öğrenci + finans kolon → ACL bloklu | ✅ `test_sql_ogrenci_blocked` |
| Ollama'ya "benim borcum ne?" | `_PERSONAL_KEYWORDS` → Claude'a yönlenir | ✅ `test_cloud_finans_keywords` |
| Finans screenshot foto | Caption filter → Vision API çağrılmaz | ✅ `test_vision_detects_finans_caption_tr` |
| Cache'e finans verisi yaz | `is_finans_cache_op` → sessizce drop | ✅ `test_cache_deny_finans_prefixes` |
| Normal sorgular etkilenmedi | Finans olmayan normal SQL → geçer | ✅ `test_sql_normal_query_passes` |

## 🚀 Veri Girişi Akışı (Neo için)

### 1. Eyotek'ten SS al
Neo SS atacak, ben Eyotek tablolarını parse edip import script'i yazacağım.

### 2. Manuel DB girişi (önerilen — güvenli)
```python
# import_finans.py — ben yazarım sen SS'yi gönderince
from db_pool import db_execute
await db_execute(
    "INSERT INTO monthly_installments (soz_no, donem, ay, yil, vade_tarihi, taksit_tutari) "
    "VALUES ($1,$2,$3,$4,$5,$6)",
    123, '2025-2026', 9, 2025, '2025-09-15', 2500.00
)
```

### 3. WhatsApp sorgulama (Neo'dan)
```
"Kurum finans nasıl"               → finans_ozet tool
"Ali Demir'in borcu ne"            → ogrenci_borc_detay(soz_no=208)
"30 günden fazla geciken kimler"   → geciken_odemeler(min_gun=30)
"Son 6 ay tahsilat trendi"         → aylik_tahsilat_trend(ay_sayisi=6)
"Zeynep'in velisine taslak hazırla"→ veli_borc_bildirim_taslak(soz_no=X, tip='nazik')
"Son 24 saat finans audit"         → finans_audit_rapor(saat=24)
```

## 🛡️ Neo'ya Özel Güvenlik Kuralları

1. **Web chat session** — Finans sorgusu varsa session 10 dk sonra timeout (sonra)
2. **2FA öneri** — Neo finans oturumu için 2. faktör (ileride, isteğe bağlı)
3. **Backup şifreleme** — pg_dump + gpg (Eylül öncesi önerilir)
4. **pgcrypto kolon şifreleme** — TC, IBAN gibi hassas alanlar (Eylül öncesi)

## 📞 Veli Bilgilendirme Workflow (HAZIR, HENÜZ KULLANMIYOR)

1. Neo: `veli_borc_bildirim_taslak(soz_no=X, mesaj_tipi='nazik')`
2. Bot taslak üretir, DB'ye `veli_iletisim` tablosuna status='draft' kaydeder
3. Neo taslağı görür, beğenirse ONAYLAR (manual WP komutu — ileride gelecek)
4. `veli_borc_bildirim_gonder(draft_id=Y)` tool'u (Faz 2'de eklenecek, şu an YOK)
5. Send rate limit: saatte max 20 veli (Meta API policy)
6. **Şu an otomatik GÖNDERİLMEZ** — sadece draft üretim

## 🔒 Kritik Saldırı Vektörleri — Kapatıldı

| Vektör | Durum |
|--------|-------|
| SQL injection ile finans tablo erişimi | sqlglot AST + regex + finans_access triple guard ✅ |
| Cache sızıntısı (analytics_cache JSON dosyası) | finans key deny ✅ |
| Ollama prompt leak (yerel model log) | finans keyword → cloud redirect + yerel prompt yasak ✅ |
| Vision sızıntı (screenshot → Anthropic) | caption filter ✅ |
| Rol eskalasyon (admin rolü kazanma) | phone whitelist — rol yeterli değil ✅ |
| SGM Orsel teknik erişimiyle finans görme | SGM_FORBIDDEN_TABLES + finans guard double ✅ |

## ⏭️ Sıradaki Adım — Neo'dan SS Beklemekte

Neo SS atacak, ben:
1. Eyotek tablolarını anlayıp → import_finans_excel.py yaz
2. İlk kayıtları test verisi ile gir (dry-run)
3. Neo confirm edince gerçek veri yüklemesi
4. İlk sorgular: "finans_ozet" ile kurum genel durum

## 📌 Bridge Durumu

- **v112 canlıda** (port 8001)
- `/health` → `{"status":"ok"}`
- Eyotek session ONLINE
- Tüm finans koruma katmanları aktif

**Sistem tamamen hazır. Neo'nun SS'ini bekliyorum.**
