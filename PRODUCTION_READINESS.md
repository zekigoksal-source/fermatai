# 🎯 FermatAI Production Readiness Scorecard

> **Belge tarihi:** 28 Nisan 2026 · **Oturum:** 25.23
> **Genel skor:** **%78** (Beta-to-Production geçiş aşaması)

---

## Genel Skor Kartı

```
A. Teknik Olgunluk      ████████████████░░░░  %75
B. Güvenlik             ██████████████████░░  %90
C. Operasyonel          ██████████████░░░░░░  %70
D. Ürün/UX              █████████████████░░░  %85
E. Veri/İçerik          █████████████████░░░  %85
F. Maliyet              ███████████████░░░░░  %75
G. Roadmap              █████████████░░░░░░░  %65

═══════════════════════════════════════════
GENEL HAZIR BULUNMUŞLUK     %78
═══════════════════════════════════════════
```

---

## A. Teknik Olgunluk — %75

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Kod kalitesi | 65 | 40+ modül, sorumluluk ayrı | 3 büyük dosya monolitik (4150/3290/1468 satır) |
| Test coverage | 50 | 138 unit + canlı senaryo | Ana bot kod için ~40 test (binlerce satır) |
| Mimari | 90 | 5 katmanlı hibrit, multi-provider, intent-aware | NORMAL_PROMPT modüler tier disabled |
| Observability | 85 | routing_stats granüler, usage_log, alert_log | Real-time UI yok |
| Performance | 85 | Cerebras 436ms, fast 5ms, %50 trafik LLM-free | Watchdog 3sn web kanalı bazen kesilme |
| Reliability | 75 | 3 LLM fallback, Redis idempotency, stale lock recovery | Eyotek VPS CDP yok |

## B. Güvenlik & Uyumluluk — %90

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| KVKK | 95 | Multi-katman koruma, 138 test PASS, 12 canlı saldırı 0 sızıntı | - |
| Auth & ACL | 95 | Telefon=kimlik, 7 rol matrisi, SQL ACL guard | acl_users manuel update |
| Audit log | 85 | eyotek_action_log, agent_conversations, routing_stats, usage_log | Long-term retention politikası yok |
| Injection defense | 95 | Test ile kanıt: prompt injection, role escalation, jailbreak red | DAN benzeri yaratıcı %100 değil |
| Rate limit | 85 | Burst detection + 1 saat ban + per-phone async lock | Cerebras spend monitoring yok |
| Backup & recovery | 80 | Daily 03:00 pg_dump, 7 gün retention, 4 seviye rollback | Off-site backup yok |

## C. Operasyonel — %70

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Deploy süreci | 80 | git push + git pull + restart, 3dk | auto_deploy.sh stash gerek |
| Monitoring | 65 | systemctl + curl manuel | Health check cron yok |
| Alarm sistemi | 30 | Kod hazır ama `ALERTS_ACTIVE=False` | Tüm alarmlar kapalı (Neo onayı bekliyor) |
| Cron jobs | 85 | backup, eyotek-daily, smart-sync, atlas-2 | Quality + spend cron yok |
| VPS kapasitesi | 95 | 8 core, 13GB serbest, %5 yük | Tek instance, multi-worker yok |
| Geri alma | 95 | 4 seviye rollback, 16+ tag, env flag | DB rollback manual |

## D. Ürün/UX — %85

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Çekirdek özellikler | 95 | Chat, plan, analiz, foto soru, sınav scrape | Veli modülü kapalı |
| Multi-channel | 90 | WP + Web Chat + Çalışmam + Admin | Mobile native yok |
| Pedagojik zeka | 75 | Sentiment, ELO, knowledge graph kuruldu | Adaptive engine üretim aktif kullanım az |
| UX olgunluk | 90 | Filler/watchdog, queue, same-tab, mobile fix | A/B kalite manuel |
| Çalışmam paneli | 80 | 7 modül aktif | Hiç gerçek kullanım yok |
| Yönetim paneli | 85 | 8 tab, 11 endpoint, Cinema palette | Real-time grafik yok |

## E. Veri & İçerik — %85

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Öğrenci verisi | 95 | 125 öğrenci, 1963 sınav, 2338 konu | LGS topic_tracker yok |
| RAG içerik | 90 | 5562 kayıt | Sözel atlandı (kurum SAY+EA) |
| Çıkmış soru | 85 | TYT 202 + AYT Sayısal 149 + AYT EA 39 = 390 | YDT yok |
| Personel/sınıf | 95 | 18 personel, 13 sınıf, 14 öğretmen takvimi | Bazı iletişim eksik |
| Tarihsel veri | 95 | 2421 etüt, 1631 rehberlik, 119 devamsızlık | Eyotek session drop'ta gecikir |
| Embedding altyapısı | 90 | pgvector 1024-dim, nomic-embed | Cerebras embed yok |

## F. Maliyet & Sürdürülebilirlik — %75

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Birim maliyet | 85 | Hibrit $0.005-0.05/mesaj | Spend monitoring yok |
| Ölçeklenebilirlik | 75 | Cerebras sınırsız, Claude $200K/ay | Tek worker bottleneck riski |
| Multi-provider | 95 | Cerebras + Groq + Ollama + Claude | Cerebras single-region (US) |
| Optimizasyon | 85 | Anthropic cache, fast_response %50 | Prompt compression yok |
| Bütçe takibi | 50 | Token-budget endpoint Cerebras pricing eklendi | Günlük alert yok |
| ROI hesaplaması | 90 | Hibrit %43 tasarruf kanıtlı | 1 günlük datası, gerçek 1 ay sonra |

## G. Roadmap & Gelecek — %65

| Alan | Skor | Durum | Boşluk |
|------|------|-------|--------|
| Yaz kampı hazırlık | 60 | Cerebras + multi-provider hazır | Yaz load test yapılmadı |
| Eylül full kapasite | 70 | Mimari kanıtlanmış, VPS rahat | Multi-worker yok |
| Yeni sezon özellikler | 80 | Veli, alarm, tercih kodu hazır (flag'ler kapalı) | Aktivasyon checklist yok |
| Teknik borç | 50 | REFACTOR_PLAN.md var, P2.1/P2.2 dokunulmadı | 3 monolitik dosya |
| Self-improvement | 85 | Atlas-2 cron çalışıyor, 5 öneri üretti | Auto-approve yok |

---

## Aciliyet/Etki Matrisi

```
            DÜŞÜK ETKİ          YÜKSEK ETKİ
        ┌─────────────────┬─────────────────────┐
ACİL    │ • Test coverage  │ • Spend monitoring  │ ← FAZ 1
        │ • Log retention  │ • Alarm aktivasyon  │
        │ • Cosmetic UI    │ • Eyotek session   │
        │                  │ • Health monitoring │
        ├─────────────────┼─────────────────────┤
ERTELE  │ • LGS topic      │ • Multi-worker      │ ← FAZ 2-3
        │ • YDT içerik     │ • Prompt compress   │
        │ • Modülerleştirme│ • Veli modülü       │
        │ • Native app     │ • Atlas auto-approve│
        └─────────────────┴─────────────────────┘
```

---

## 4 Fazlı Vizyon

### Faz 1 — Mayıs 2026 (Stabilizasyon)
**Hedef:** %78 → %85
- Spend Monitoring Cron (1 saat)
- Alarm Sistemi Aktivasyonu (Neo onayı + 2 saat)
- Health Check Cron (1 saat)
- Dashboard Real-time Widget (3 saat)

### Faz 2 — Haziran 2026 (Yaz Kampı Hazırlık)
**Hedef:** %85 → %90
- Sentetik Load Test (1 gün)
- Eyotek Session Reliability (1 gün)
- Multi-worker Async (2 gün)
- Prompt Compression Pilot (3 gün)
- Conversation Quality Cron (1 saat)

### Faz 3 — Temmuz-Ağustos 2026 (Pilot + İterasyon)
**Hedef:** %90 → %93
- Yaz Kampı Pilot (20-30 öğrenci)
- Atlas-2 Auto-Approve Test
- Veli Modülü Aktivasyon (5 veli pilot)
- Tercih Robotu Hazırlık (YKS sonrası)
- Modülerleştirme P2.1 (fast_responses)

### Faz 4 — Eylül 2026 (Full Capacity)
**Hedef:** %93 → %95+
- 120 öğrenci canlı, multi-worker
- Modülerleştirme P2.2 (fermat_core)
- system_prompts.py modülerleştirme
- Web Chat Faz 2 (streaming, history search)
- Adaptive Engine aktif (foto entegrasyon)

---

## KPI Tablosu

| Metrik | Şu An | Mayıs | Haziran | Eylül |
|--------|-------|-------|---------|-------|
| Hazır bulunmuşluk | %78 | %85 | %90 | %95 |
| Aktif öğrenci | 3 | 5-8 | 20 | 120 |
| Aylık API maliyet | ~$30 | ~$50 | ~$100 | ~$172 |
| Mesaj/gün | ~50 | ~100 | ~300 | ~1080 |
| Uptime | %99.5 | %99.7 | %99.9 | %99.95 |
| Atlas-2 öneriler/hafta | yeni | 5-10 | 15-20 | 30+ |
| KVKK sızıntı | 0 | 0 | 0 | 0 |
| Test coverage | 138 | 200 | 300 | 500 |

---

## Stratejik Kararlar (Neo onayı bekliyor)

| Karar | Önerim | Zaman |
|-------|--------|-------|
| Alarm sistemi aktif et | EVET | Mayıs |
| Multi-worker kur | EVET | Haziran |
| Veli modülü aktif et | YAVAŞ pilot | Temmuz |
| Modülerleştirme refactor | Yaz kampı sonrası | Ağustos |
| Atlas-2 auto-approve | TEDBİRLİ | Temmuz pilot, Eylül tam |
