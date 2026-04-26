# 🛠️ FermatAI Refactor Planı

> **Hazırlanma:** 26 Nisan 2026 (Oturum 25.11 audit sonrası)
>
> Bu plan, sistem stabil çalışırken **kademeli + test-edilebilir** refactor için.
> Her madde bağımsız, kendi içinde test edilebilir, regression riski sınırlı.
>
> **Şart:** Her refactor öncesi pytest **ALL PASS** olmalı (şu an 53/53).
> Refactor sonrası test sayısı artmalı, mevcut testler kırılmamalı.

---

## 🎯 Öncelik Sırası

### 🔴 P1 — Token Tasarrufu (yüksek etki, düşük risk)

#### 1.1 Ölü Tool Description Compact (~3000 token tasarruf)
**Sorun:** 64 tool'dan 25+ tanesi son 30 günde ≤2 çağrı aldı, ama her sistem
prompt'ta tam description ile yer alıyor.

**Etki:** Her Claude çağrısında ~3000 gereksiz token (input).
- Aylık: ~3000 × 500 mesaj × $3/1M = **~$4.5/ay tasarruf**
- Cümle başı response süresi de iyileşir (input parsing)

**Plan:**
```python
# tool_definitions.py — yeni structure
TOOLS_FULL = [...]  # mevcut 64 tool tam tanım
TOOLS_COMPACT = [...]  # 49 aktif tool + 15 dead'in 1 satır description

def get_tools(role: str = "ogrenci") -> list:
    # Role-based filtering: ogrenci finans tool gormez
    # Dead tool'lar default GIZLI, force_full=True ile tam kullanır
    if role == "admin":
        return TOOLS_FULL
    return TOOLS_COMPACT
```

**Risk:** ORTA — eski Claude oturumları gizli tool'u bilmediği için çağırmaz.
İleride Neo isterse tool'u tekrar açabilir.

**Önkoşul:** Test coverage genişletilmiş olmalı (DONE — 53 test).

**Tahmini efor:** 1 oturum (~2 saat)

#### 1.2 System Prompt Cleanup
**Sorun:** `system_prompts.py` 1418 satır, içinde:
- Eski oturum yorumları (Oturum 18, 19, 20...)
- Tekrar eden ASLA/YASAK kuralları
- Atlas-2 mockup notları

**Plan:** Sadece KURALLAR + SCHEMA + TOOL_KULLANIMI + ROL_TANIMLARI bırak. ~500
token tasarruf.

**Risk:** ORTA — her satır bir kural olabilir, dikkatli yapılmalı.

---

### 🟡 P2 — Mimari Sadeleştirme (orta etki, orta risk)

#### 2.1 fast_responses.py Modülerleştirme
**Sorun:** 3289 satır tek dosya, 60+ pattern handler, navigasyon zor.

**Plan:**
```
fast_responses/
├── __init__.py          # try_fast_response orchestrator
├── ogrenci.py            # ~1500 satır - öğrenci pattern'ları
├── ogretmen.py           # ~400 satır - öğretmen pattern'ları
├── admin.py              # ~300 satır - admin pattern'ları
├── yks_lgs.py            # ~400 satır - sınav format/tarih
├── foto_handlers.py      # ~200 satır - foto soru hak/limit
├── help_menu.py          # ~200 satır - yardım/kabiliyet menü
└── shared.py             # ~300 satır - ortak helpers (_tr_norm, _q vs)
```

**Test stratejisi:** Mevcut testler (test_format_whatsapp, paraphrase) sürdür,
yeni testler her alt-modül için.

**Risk:** YÜKSEK — import path değişiklikleri, fast_responses çağıran 30+ yer.

**Önkoşul:** test_paraphrase_coverage.py reactivate (oturumlar 18'de %100 idi).

**Tahmini efor:** 2 oturum (~4-6 saat)

#### 2.2 fermat_core_agent.py Bölme
**Sorun:** 4150 satır, agent class + 60+ tool wrapper + helper fonksiyonlar.

**Plan:**
```
fermat_core/
├── agent.py              # ~1500 satır - FermatCoreAgent class + run()
├── tool_wrappers.py      # ~1500 satır - _tool_* fonksiyonlar
├── tool_dispatcher.py    # ~200 satır - TOOL_DISPATCH dict + dispatch
├── claude_loop.py        # ~600 satır - Claude tool-calling loop
├── enrichment.py         # ~300 satır - context enrichment helpers
└── format_helpers.py     # ~150 satır - _clean_response, _clean_ollama_format
```

**Risk:** ÇOK YÜKSEK — ana akış. Hatalı refactor sistem cevap vermez.

**Önkoşul:**
- E2E integration test suite (en az 20 senaryo)
- Bridge restart sonrası canlı test prosedürü
- Rollback hazır (eski dosya `.bak` olarak)

**Tahmini efor:** 3-4 oturum

#### 2.3 whatsapp_bridge.py Bölme
**Sorun:** 4215 satır, FastAPI app + scheduler + helper fonksiyonlar.

**Plan:**
```
bridge/
├── app.py                # FastAPI app + lifespan
├── webhook.py            # Meta webhook handler
├── scheduler.py          # _run_scheduled_tasks (cron'lar)
├── send.py               # send_wa_message + outreach
├── intent_processor.py   # mesaj process pipeline
└── admin_commands.py     # WA admin komutları (token, sync, vs)
```

**Risk:** YÜKSEK — webhook + scheduler ana sistem.

**Tahmini efor:** 2-3 oturum

---

### 🟠 P2.5 — Modüler Prompt Mimarisi (Neo 25.14k önerisi, YÜKSEK ETKI)

**Sorun:** Şu an her çağrıda 28k FERMATAI prompt + 6k tool tanımı + dynamic_context (~37k) gönderiliyor. "Limit nedir" diyene de "plan yap"a da AYNI 28k. Cache var ama ölçek değişmiyor.

**Endüstri standardı isimler:** Prompt Routing, Tool Subset Routing, Lazy Module Loading

**Önerilen mimari:**
```
3-tier system_prompt + tool subset routing
├─ TIER_LIGHT  (~6k):  KURALLAR + ACL + 5 tool (sohbet, kavramsal, basit data)
├─ TIER_NORMAL (~18k): + plan/analiz tools + scenario hazırlıkları
└─ TIER_FULL   (~28k): + finans tools + admin Atlas + Easter egg (mevcut)
```

**Tier seçim mantığı (routing_engine'e ek):**
```python
def choose_tier(intent, role, lane):
    if role in ("admin", "mudur") or intent == "finans": return "full"
    if lane in ("kavramsal", "sohbet", "selamlama"):     return "light"
    if intent in ("plan", "analiz", "tool_yazma"):       return "normal"
    return "normal"  # default safe
```

**Kazanım tahmini (1000 mesaj/gün):**
| Sorgu tipi | Şu an | Modüler | Tasarruf |
|---|---|---|---|
| Kavramsal | 28k | 6k | -78% |
| Plan | 28k | 18k | -36% |
| Admin | 28k | 28k | 0 |

Aylık Claude maliyeti **~$8 → ~$3** (cache dahil). Asıl kazanım: **Groq tool-calling 12k TPM aşılmaz**, bot kuralları seyrelmez (small prompt = better attention).

**Riskler:**
1. Tier yanlış seçilirse → bot kural unutur (KVKK ihlal, finans sızıntısı)
2. Lane classifier hassas değil (border case'ler)
3. A/B test gerek (tam prompt vs modüler kalite kıyaslaması)

**Yapım sırası:**
1. `system_prompts.py` → `system_prompt_modules.py` modülerleştir (CORE, TOOLS, SCENARIO, FINANS, EASTER, ATLAS bloklarına ayır)
2. `tier_selector.py` yaz — intent + lane + role → tier dön
3. Tool definitions → tier bazlı subset (`get_tools_for_tier()`)
4. fermat_core_agent.py: messages.create öncesi tier seç + uygun blokları birleştir
5. A/B test 100 mesaj — kalite skoru >0.95 ise canlıya
6. Conversation_quality_analyzer ile haftalık denetim

**Test coverage zorunlu:** Her tier için en az 20 senaryo (KVKK, finans, kişisel veri sızma, kural ihlal testleri)

---

### 🟢 P3 — Cosmetic / Geleceğe Yatırım

#### 3.1 'ollama' Legacy Naming
**Yapıldı:** Oturum 25.11'de partial fix:
- `_local_provider` artık dinamik ("groq" veya "ollama")
- query_cache `source=_local_provider` (hardcoded değil)
- format_for_whatsapp 'groq' source destekli

**Kalan:**
- `tools_used` array hala `"groq_local"` veya `"ollama_local"` yazıyor
- `format_for_whatsapp(source="ollama")` çağrı bazı yerlerde kalmış
- Function name `_clean_ollama_format` → `_clean_local_format`

**Etki:** Sıfır işlevsel değişiklik, sadece okunabilirlik.

#### 3.2 _DB_POOL Cleanup
**Yapıldı:** Oturum 25.11 — shutdown _DB_POOL NameError düzeltildi.

**Kalan:** Bridge restart loglarında "deprecation warning" var:
```
node:735139 [DEP0169] DeprecationWarning: url.parse() ...
```
Node.js OAuth kütüphanesinden geliyor, bizim kod değil. Cosmetic.

#### 3.3 Test Coverage 53 → 100+
**Şu an:** 53 test (8 modül).

**Hedef test eklemeleri:**
- `test_groq_handler.py` — Groq client integration (mocked)
- `test_chat_local_async.py` — uvloop uyumluluk
- `test_dashboard_api.py` — auth + endpoint smoke
- `test_knowledge_graph.py` — concept_nodes seed + mastery
- `test_predictive_full.py` — DB-bağımlı vakalar (testdb fixture)
- `test_acl.py` — role_access matrix
- `test_security.py` — KVKK identity_lock end-to-end

**Tahmini efor:** 2 oturum

---

## 🚦 Refactor Yapım Sırası (Önerilen)

```
1. P1.1  Tool compact         (1 oturum)  → token tasarruf
2. P3.3  Test coverage 100+   (2 oturum)  → güvenlik ağı
3. P1.2  System prompt cleanup (1 oturum) → token tasarruf
4. P2.1  fast_responses böl   (2 oturum)  → bakım kolaylığı
5. P2.2  fermat_core_agent böl (3 oturum) → ana yenileme
6. P2.3  whatsapp_bridge böl  (2 oturum)  → tamamla
```

**Toplam efor:** ~11 oturum (2-3 hafta yarı zamanlı)

**Süreç:**
- Her madde sonrası canlı test + commit + VPS sync + 24h gözlem
- Rollback prosedürü hazır (git reset --hard <prev>)
- Test coverage hiçbir adımda azalmamalı

---

## ⚠️ Risk Yönetimi

### Refactor öncesi checklist
- [ ] Tüm testler pass (`pytest tests/ -v`)
- [ ] Production'da kritik bug yok (24h log temiz)
- [ ] VPS backup tamam (fermatai-backup.timer son çalışma)
- [ ] Eski versiyon `.bak` olarak hazır

### Refactor sırası kontrol
- [ ] Her ayrılan modül için min 5 test
- [ ] Import path değişikliği grep ile bulundu
- [ ] Mevcut testler hala pass

### Refactor sonrası verify
- [ ] pytest test sayısı artmış (azalmamış)
- [ ] Bridge restart sonrası `/chat` 200
- [ ] 5 e2e test mesajı (admin + öğrenci + frustration)
- [ ] routing_stats DB'de 1 saatlik trafik dağılımı normal
- [ ] KALDIGIM güncellendi

---

## 📌 Tamamlanan (referans)

| # | Yapıldı | Oturum | Etki |
|---|---------|--------|------|
| ✅ Identity_lock (KVKK) | 25.8 | KVKK güvenliği |
| ✅ sinav_takvimi tek kaynak | 25.8 | Tutarsızlık fix |
| ✅ Fast response math context | 25.8 | UX |
| ✅ Mezun ayrımı | 25.8 | Sıralama |
| ✅ Adaptive Engine | 25.9 | Pedagojik |
| ✅ Predictive Model | 25.9 | YKS tahmin |
| ✅ Knowledge Graph | 25.9 | Konu ağı |
| ✅ Atlas-2 | 25.9 | Self-improving |
| ✅ Dashboard | 25.9 | Admin paneli |
| ✅ T2-T6 backup/sync/test/JSON/token | 25.9 | Ops |
| ✅ Groq Lane Fix | 25.10 | %30 trafik |
| ✅ uvloop fix | 25.11 | Groq production CANLI |
| ✅ admin_notify gece yasak | 25.11 | UX kritik |
| ✅ MIMARI.md | 25.11 | Token tasarruf |
| ✅ Test 53/53 | 25.11 | Güvenlik ağı |

---

## 🎁 Bonus: Atlas-2 Self-Refactor

**Hedef:** Bot kendi kodunu okusa ve refactor önerse.

```python
# prompt_optimizer.py'a eklenebilir
async def analyze_codebase_for_refactor():
    # 1. Her dosya için LoC + cyclomatic complexity
    # 2. Tool kullanım frequency (DB'den)
    # 3. Groq 70B'ye ver: "Bu kod ölü mü, refactor önerin?"
    # 4. prompt_suggestions tablosuna refactor önerileri
```

Bu plan tamamlandığında bot **kendi kendini iyileştiren** sistem olur.
Şimdilik fikir, P2-P3 sonrası uygulanabilir.
