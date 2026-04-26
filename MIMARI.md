# 🗺️ FermatAI Sistem Mimarisi (Token Tasarruf Haritası)

> Bu dosya **Claude Code (LLM dev partner) için optimize edilmiş** sistem haritası.
> Her oturumda bu dosyaya bakınca **hangi dosyada ne olduğunu** Read yapmadan bilir,
> token maliyeti %20-30 azalır (Graphify alternatifi).
>
> **Son güncelleme:** 26 Nisan 2026 (Oturum 25.11)

## 🎯 Hızlı Referans

```
WhatsApp / Web Chat → whatsapp_bridge.py / web_chat.py
                          ↓
                     fermat_core_agent.py (ana beyin)
                          ↓
                     routing_engine.decide_route → "fast" | "local" | "claude"
                          ├── fast → fast_responses.py (template)
                          ├── local → llm_router.chat_local_async (Groq 70B)
                          └── claude → Anthropic Sonnet 4.6 + tool calls
                          ↓
                     PostgreSQL (asyncpg pool, db_pool.py)
                          ↓
                     Eyotek (eyotek_wrapper.py, Playwright CDP)
```

---

## 📁 Dosya Envanteri (Kategori Bazlı)

### 🔵 1. CORE / ENTRY (giriş noktaları, en kritik)

| Dosya | LoC | Görev | Ana Exports |
|-------|-----|-------|-------------|
| **whatsapp_bridge.py** | 4215 | FastAPI app, WhatsApp webhook, scheduler, lifespan | `app`, `_run_scheduled_tasks`, `send_wa_message` |
| **fermat_core_agent.py** | 4150 | Ana ajan: routing + tool dispatch + Claude calls | `FermatCoreAgent.run()`, `TOOL_DISPATCH` |
| **fermat_start.py** | 921 | Tek dosya başlatıcı (Chrome+bridge+keeper) | CLI entrypoint |
| **web_chat.py** | 2297 | Web chat UI + admin/conversations endpoint | `router`, `_extract_token`, `_require_admin` |
| **web_chat_auth.py** | ~280 | OTP + session yönetimi (web chat) | `verify_otp`, `get_session`, `logout` |
| **llm_router.py** | 1280 | LLM seçici (Groq/Ollama/Claude) | `LLMRouter`, `chat_local_async`, `classify_complexity` |
| **routing_engine.py** | 240 | Mesaj routing kararı (tek karar noktası) | `decide_route`, `detect_frustration` |
| **groq_lanes.py** | 270 | 7 Groq-safe lane classifier (Oturum 25.10) | `classify_lane`, `get_lane_system_addon` |
| **tool_definitions.py** | 1436 | 64 Claude tool tanımı (TOOLS list) | `TOOLS` |
| **system_prompts.py** | 1430 | Role-aware Claude system prompt | `build_system_prompt`, role kuralları |
| **fast_responses.py** | 3289 | Template yanıt motoru (Fast lane) | `try_fast_response`, `ogrenci_zayif_konular` |
| **format_whatsapp.py** | ~280 | WP format zorlayıcı (markdown→WA, chart cleaner) | `format_for_whatsapp` |

### 🟢 2. TOOLS (modüler tool implementasyonları)

| Dosya | Görev |
|-------|-------|
| `tools/finans.py` | Finans tool'ları (Neo-only) — finans_ozet, geciken_odemeler, sezon_kiyasla |
| `tools/kaynak.py` | Kaynak/RAG tool'ları — search_curriculum, ogm_yonlendir |
| `tools/ogretmen.py` | Öğretmen tool'ları — ogretmen_brief, etut_takvimi |
| `tools/tercih.py` | YKS Tercih Robotu (sezona bağlı) — tercih_listesi_uret |

### 🟣 3. AI / ADAPTIVE / PREDICTIVE (Oturum 25.9 mega genişleme)

| Dosya | Görev | Tablo |
|-------|-------|-------|
| **adaptive_engine.py** | ELO + SM-2 + Misconception | `student_topic_elo`, `student_review_schedule`, `student_misconceptions` |
| **predictive_model.py** | YKS puan tahmin (linear trend) | `student_predictions` |
| **knowledge_graph.py** | 77 concept node + 72 edge | `concept_nodes`, `concept_edges`, `student_concept_mastery` |
| **prompt_optimizer.py** | Atlas-2 daily prompt iyileştirme | `prompt_suggestions` |
| **adaptive_difficulty.py** | (legacy) eski zorluk takibi | — |
| **insight_extractor.py** | Konuşmadan öğrenci insight çıkarma | `student_insights` |
| **insight_backfill.py** | Eski konuşmaları toplu insight çıkar | — |
| **sentiment_tracker.py** | Duygu sinyali tespit + rehber alarm | `alert_log` |
| **conversation_quality_analyzer.py** | Groq 70B konuşma kalite denetimi | — |
| **ollama_arbiter.py** | Belirsiz mesajlarda hakem | — |
| **self_observer.py** | Kalite log (her cevap sonrası) | `quality_log` |
| **atlas_lifecycle.py** | Atlas observation yaşam döngüsü | `atlas_observations`, `atlas_suggestions` |

### 🟠 4. EYOTEK / SYNC / SCRAPE

| Dosya | Görev |
|-------|-------|
| **eyotek_wrapper.py** | Playwright CDP — Eyotek okuma/yazma (3465 satır) |
| **eyotek_auto_login.py** | CapSolver Turnstile çözüm + otomatik giriş |
| **eyotek_mobile_tunnel.py** | (legacy) noVNC mobil köprüsü |
| **session_keeper.py** | Eyotek session canlı tutma (CDP heartbeat) |
| **smart_sync.py** | Incremental sınav sync (delta-aware) |
| **sync_attendance.py** | Yoklama günlük sync |
| **sync_exams.py** | Sınav verisi sync |
| **sync_missing_students.py** | Eksik öğrenci verisi tarama |
| **scrape_*.py** | (10+ dosya) — başlangıç scrape script'leri |
| **fill_missing_nets.py** | Sınav istatistik sayfasından net tarama |

### 🟡 5. DATA / RAG / DB

| Dosya | Görev |
|-------|-------|
| **db_pool.py** | asyncpg connection pool helper | `get_pool`, `db_fetch`, `db_execute` |
| **analytics_cache.py** | 10 kategori önceden hesap (1h cache) |
| **query_cache.py** | Query embedding-based cache |
| **rag_engine.py** | pgvector semantic arama |
| **rag_content_builder.py** | Claude/Groq ile RAG içerik üretici |
| **usage_tracker.py** | Mesaj kullanım log (token, source, time) |
| **pdf_*.py** | PDF import/export/archive |
| **build_topic_tracker.py** | Sınav verisinden zayıf konu çıkarma |

### 🔴 6. ADMIN / DASHBOARD

| Dosya | Endpoint / Görev |
|-------|------------------|
| **dashboard_api.py** | `/admin/dashboard`, `/admin/api/*` (8 tab) |
| **dashboard_ui.html** | HTMX + Chart.js dashboard UI |
| **admin_notify.py** | Saat-aware bildirim helper (gece WP yasak) |
| **admin_dashboard.py** | (legacy?) eski dashboard |
| **admin_sync_commands.py** | WP admin komutları (token, sync, vs) |
| **jarvis_admin.py** | Neo morning brief, Atlas trend |
| **secure_messenger.py** | Güvenli WP gönderim (onay+hedef+log) |

### 🔘 7. KONUSMA / MEMORY / FLOW

| Dosya | Görev |
|-------|-------|
| **conversation_memory.py** | Öğrenci context cache + identity_lock (KVKK) |
| **conversation_flow.py** | Filler + watchdog + queue (UX) |
| **conversation_viewer.py** | HTML konuşma viewer (admin) |
| **session_tracker.py** | Per-phone session state |
| **system_awareness.py** | KALDIGIM.md okuma + bot self-awareness |

### 🟤 8. ENRICHMENT / KISILESTIRME

| Dosya | Görev |
|-------|-------|
| **kisisellestirme.py** | Mesajdan öğrenci sinyali çıkarma |
| **classroom_metrics.py** | Sınıf bazlı performans raporu |
| **time_analytics.py** | Saat bazlı kullanım analizi |
| **feedback_loop.py** | User feedback toplama |
| **role_briefs.py** | Rol başına özet (öğrenci/öğretmen/rehber) |
| **role_access.py** | ACL — tool izin matrisi |

### 🔧 9. SCHEDULING / ALERT

| Dosya | Görev |
|-------|-------|
| **alert_system.py** | Alarm motor (devamsızlık, net düşüş, duygu) |
| **odev_scheduler.py** | Ödev hatırlatıcı |
| **session_keeper.py** | Eyotek session keeper |

### 🟫 10. UTIL / HELPER

| Dosya | Görev |
|-------|-------|
| **sinav_takvimi.py** | YKS/LGS tarihleri TEK KAYNAK (Oturum 25.8) |
| **groq_handler.py** | Groq AsyncClient wrapper |
| **groq_lanes.py** | 7 Groq-safe lane classifier |
| **capsolver_helper.py** | CapSolver Turnstile API |
| **pattern_loop_guard.py** | Same handler 2x → Claude eskale |
| **motivation_library.py** | Motivasyon mesaj template kütüphanesi |
| **response_templates.py** | Genel response sabitleri |
| **lgs_helper.py** | LGS özel akış |
| **study_plan_builder.py** | Çalışma planı zengin context |
| **visual_generator.py** | Grafik/chart üretici |

---

## 🌐 Endpoint Haritası

### WhatsApp Bridge (port 8001)
- `POST /webhook` — Meta WhatsApp webhook (mesaj gelişi)
- `GET /webhook` — Meta webhook verify

### Web Chat (`/chat` prefix)
- `GET /chat` — Web chat UI
- `POST /chat/login` — Telefon + OTP başlangıç
- `POST /chat/verify` — OTP doğrulama
- `POST /chat/send` — Mesaj gönder
- `GET /chat/me` — Profil
- `GET /chat/admin/conversations` — Konuşma viewer (admin)
- `GET /chat/archive` — Arşiv

### Dashboard (`/admin` prefix)
- `GET /admin/dashboard` — HTML dashboard (8 tab)
- `GET /admin/api/notifications` — Bildirim listesi
- `POST /admin/api/notifications/{id}/read` — Okundu işaretle
- `GET /admin/api/routing-stats` — Routing dağılımı
- `GET /admin/api/usage-summary` — Kullanım istatistik
- `GET /admin/api/cohort-analysis` — Sınıf karşılaştırma
- `GET /admin/api/teacher-effectiveness` — Öğretmen verim
- `GET /admin/api/token-budget` — Per-user maliyet
- `GET /admin/api/atlas-suggestions` — Atlas-2 önerileri
- `POST /admin/api/atlas-suggestions/{id}/approve|reject|apply`
- `GET /admin/api/student/{soz_no}/prediction|knowledge-graph|adaptive-summary`

### Auth shortcuts (URL `?token=`)
- `?token=fermat_agent_secret_2026` — admin session bypass (Neo dev)

---

## 🔐 Güvenlik Mimarisi

```
1. Telefon = Kimlik (KVKK temeli)
2. ACL Matrix (role_access.py) — tool bazlı izin
3. SQL ACL (query_analytics) — tablo/kolon filtre
4. Identity Manipulation Lock (conversation_memory.py)
   → "Ben aslında X" / "X hasta, ben Y" → sensitive data lock
5. LLM Prompt ACL (system_prompts.py) — son savunma hattı
6. Bilinmeyen Numara Engeli (whatsapp_bridge.py)
7. Flood Koruma (30+/dk → 1h ban)
8. Frustration Intercept (routing_engine) → Claude eskale
9. URL Token Auth (web_chat._extract_token) — ADMIN_API_KEY
10. Quiet Hours (admin_notify.py) — gece WP yasak
```

---

## ⏰ Cron / Systemd Timer Haritası

| Timer | Saat | Dosya | Görev |
|-------|------|-------|-------|
| **fermatai-bridge** | (always) | systemd | Ana servis |
| **fermatai-eyotek-daily** | 04:00 UTC (07:00 IST) | `eyotek_auto_login.py` | CapSolver giriş |
| **fermatai-backup** | 03:00 UTC | `vps_setup/scripts/backup_full.sh` | DB+env tarball |
| **fermatai-smart-sync** | Mon/Thu 04:30 UTC | `smart_sync.py` | Sınav delta sync |

### Bridge in-app scheduler (`whatsapp_bridge.py:_run_scheduled_tasks`)
| Saat (UTC) | Görev | Modül |
|------------|-------|-------|
| Her 30dk | Analytics cache refresh | `analytics_cache` |
| **02:00** | **Atlas-2 prompt analiz** | `prompt_optimizer.analyze_and_suggest` |
| 02:30 | Eyotek etüt sync (gece) | `eyotek_knowledge.scrapers.etut_sync` |
| **03:30** | **KG mastery refresh (ELO→mastery)** | `knowledge_graph.update_student_mastery_from_elo` |
| 03:00 | Student profile v2 nightly refresh | `student_profile_v2` |
| **Pazar 04:00** | **Predictive batch (200 ogrenci)** | `predictive_model.predict_all_students` |
| 8/14/20 | Duygu/motivasyon takip | `sentiment_tracker.check_and_alert_rehber` |
| 8 | Ödev hatırlatıcı | `odev_scheduler` |
| 9/13/19/23 | Yoklama sync | `sync_attendance.run_attendance_sync` |
| 9:15 | Sync health check | `data_freshness` query |
| 20 | Daily report | `daily_report.generate_and_send_report` |
| 20 (Pzt) | Time analytics + Jarvis weekly | `time_analytics`, `jarvis_admin` |

---

## 🎯 Tool Envanteri (gerçek kullanım frequency, son 30g)

### 🟢 Aktif top 20 (>15 çağrı)
1. `query_analytics` (1480) — Generic SQL
2. `fast_response` (685) — Template
3. `ollama_local` (256) — Yerel LLM
4. `get_student_analytics` (130) — Öğrenci profil
5. `search_students` (123) — İsim arama
6. `list_exam_questions` (64) — Çıkmış soru katalog
7. `search_curriculum` (64) — RAG arama
8. `send_exam_image` (46) — Soru görseli
9. `get_ayt_analysis` (39) — AYT detay
10. `get_recent_system_updates` (31) — KALDIGIM
11. `get_class_summary` (29) — Sınıf özet
12. `build_study_plan_context` (24) — Plan veri
13. `get_class_plan` (22) — Ders programı
14. `query_cache` (22) — Embedding cache
15. `calculate_yks_score` (20) — Puan hesabı
16. `claude_vision` (14) — Foto analiz
17. `error_fallback` (14) — Hata
18. `check_teacher_availability` (14) — Öğretmen müsait
19. `execute_eyotek_action` (12) — Etüt yazma
20. `fizik`/`kimya`/`matematik`/`biyoloji` (44) — Konu rotaları

### 🔴 ÖLÜ/AZ KULLANIM (≤5 çağrı, 30g)
- `youtube_oner` (1), `get_career_info` (1), `plan_kaydet` (1), `plan_getir` (1)
- `transfer_failure_analiz` (1), `proaktif_sgm_kademe_bildirimi` (1)
- `ogrenci_borc_detay` (1), `aylik_borc_detay` (2), `geciken_odemeler` (2)
- `web_upload` (2), `eyotek_read` (2), `pedagojik_koc` (2), `puan_tahmin` (2)
- `konu_kaynak_paketi` (2), `ogrenci_nereye_girebilir` (2)
- `ogm_yonlendir` (3), `hedef_bolum_ara` (3), `plan_gun_guncelle` (3)
- `counsellor_brief` (4), `ders_konu_dagilimi_raporu` (4)
- `sezon_kiyasla` (4), `aylik_tahsilat_trend` (4)

### 🆕 YENİ (Oturum 25.9 — henüz kullanım yok)
- `predict_yks_score` — YKS puan tahmin
- `get_adaptive_summary` — ELO+SM-2 özeti
- `get_knowledge_graph` — Konu ağı
- `observe_student_answer` — Soru sonrası 3 katmanı güncelle

---

## 💾 Önemli DB Tabloları (özet)

### Öğrenci verisi
- `students` (125) — temel profil, soz_no PK
- `staff` (18) — personel
- `acl_users` — telefon→rol map
- `attendance` — günlük yoklama
- `student_exams` (3631) — sınav bazlı detay
- `student_exam_analysis` — birleştir analiz
- `student_topic_tracker` — zayıf konu
- `devamsizlik_sayisi` (119) — toplam saat
- `counsellor_notes` (1631) — rehberlik notu

### Etkileşim
- `agent_conversations` — tüm WP/web mesajları
- `usage_log` — token + source + time
- `routing_stats` — fast/groq/claude dağılım
- `student_insights` — duygu/motivasyon sinyali
- `alert_log` (290+) — alarm geçmişi

### Yeni (Oturum 25.9)
- `student_topic_elo` — ELO rating per konu
- `student_review_schedule` — SM-2 tekrar zamanlaması
- `student_misconceptions` — kavram yanılgısı
- `student_predictions` — haftalık YKS tahmin snapshot
- `notifications` — Dashboard bildirim merkezi
- `prompt_suggestions` — Atlas-2 öneri kuyruğu
- `concept_nodes` (77) — YKS müfredat
- `concept_edges` (72) — ön koşul ilişkileri
- `student_concept_mastery` — öğrenci × konu ustalık

### Sezona bağlı
- `tercih_profil`, `tercih_listesi`, `universite_taban` (35,584)
- `sistem_ayar` (TERCIH_DONEMI_ACTIVE flag)

---

## 🚀 Geliştirme Akış Önerileri (Claude Code için)

### Yeni özellik eklerken ne dosyaya bak?
| Görev | Dosya |
|-------|-------|
| Yeni Claude tool | `tool_definitions.py` (TOOLS) + `fermat_core_agent.py` (TOOL_DISPATCH + wrapper) |
| Fast response pattern | `fast_responses.py` |
| Routing kuralı | `routing_engine.py` veya `groq_lanes.py` |
| Yeni cron | `whatsapp_bridge.py:_run_scheduled_tasks` |
| Yeni dashboard endpoint | `dashboard_api.py` |
| WhatsApp format | `format_whatsapp.py` |
| Yeni DB tablo | `eyotek_agent/schema_*.sql` veya inline DDL |
| ACL kuralı | `role_access.py` + `system_prompts.py` |
| Bot context (öğrenci) | `conversation_memory.py:get_student_context` |

### Bug bulurken ne dosyaya bak?
| Sorun | İlk bakılacak |
|-------|---------------|
| Mesaj cevap vermiyor | `whatsapp_bridge.py` webhook + `fermat_core_agent.run` |
| Yanlış routing | `routing_engine.decide_route` + `llm_router.classify_complexity` |
| Halüsilasyon | `system_prompts.py` SCHEMA GUARDRAIL + `fermat_core_agent` quality check |
| KVKK ihlali | `conversation_memory.py` identity_lock + `system_prompts.py` ÖĞRENCİ |
| Eyotek sync fail | `eyotek_auto_login.py` + `session_keeper.py` |
| Dashboard 404 | `dashboard_api.py` router prefix `/admin` (web_chat ise `/chat/admin`) |

---

## ⚠️ Bilinen Sorunlar / Refactor Adayları

| Sorun | Dosya | Plan |
|-------|-------|------|
| 4215 satır tek dosya | `whatsapp_bridge.py` | Webhook + scheduler ayır |
| 4150 satır tek dosya | `fermat_core_agent.py` | Tool dispatcher + run() ayır |
| 3289 satır tek dosya | `fast_responses.py` | 5+ alt-modül (ogrenci/ogretmen/admin/yks/foto) |
| 64 tool — 25+ ölü | `tool_definitions.py` | Compact description (~3000 token tasarruf) |
| 'ollama' legacy isim | Çeşitli | 'local' veya 'groq' yeniden adlandır |

---

## 🌍 VPS Erişim

- **IP:** `116.203.117.106` (Hetzner Nuremberg)
- **User:** `neo` (root login KAPALI)
- **Key:** `C:\Users\zekig\.ssh\id_ed25519_fermatai`
- **DNS:** `api.fermategitimkurumlari.com` → 116.203.117.106
- **Service:** `fermatai-bridge.service` (systemd)
- **DB:** Docker `fermat_postgres` container, schema=`public`

```bash
# Hızlı bağlantı
ssh -i C:/Users/zekig/.ssh/id_ed25519_fermatai neo@116.203.117.106
# Service restart
sudo systemctl restart fermatai-bridge
# Log
sudo journalctl -u fermatai-bridge -n 50 --no-pager
```

---

## 📚 Dokümantasyon İlgili Dosyalar

| Dosya | İçerik |
|-------|--------|
| `KALDIGIM.md` | Session continuity (her oturum güncellenir) |
| `CLAUDE.md` | Proje hafızası (sabit) |
| `MIMARI.md` | (bu dosya) Dosya/modül haritası |
| `vps_setup/MIGRATION_PLAN_VPS.md` | VPS göç planı |
| `KONUSMA_VIEWER_README.md` | Conversation viewer kullanım |

---

> **Token tasarruf prensibi:** Yeni Claude oturumunda önce bu dosyaya bak (~5KB read).
> Hangi dosyada ne olduğunu bilirsen, gereksiz `Read` çağrıları yapmazsın.
> Tahmini tasarruf: oturum başına ~10-20K token.
