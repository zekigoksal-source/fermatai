-- =====================================================
-- 28 Nisan 2026 — 5 yeni özellik altyapısı (Oturum 25.28)
-- WP gönderim KAPALI flag, sadece queue + admin görsün
-- =====================================================

-- ─── F1: Live Teacher Briefing ───────────────────────────────────────────
-- Her öğretmenin sınıfa girmeden önce 15-30dk önce üretilen ön brief.
-- WP_DELIVERY_ACTIVE=False olduğu sürece sadece DB'ye yazılır, gönderilmez.
CREATE TABLE IF NOT EXISTS teacher_briefing_queue (
    id            SERIAL PRIMARY KEY,
    teacher_id    TEXT,                      -- staff.eyotek_id
    teacher_name  TEXT NOT NULL,
    teacher_phone TEXT,
    class_name    TEXT,                      -- '12 SAY' vs.
    lesson_label  TEXT,                      -- 'Fizik Etüt 14:45'
    scheduled_for TIMESTAMPTZ NOT NULL,      -- dersin başlama zamanı
    brief_payload JSONB NOT NULL,            -- {risk_students:[], focus_topics:[], wins:[], stats:{}}
    rendered_text TEXT,                      -- WP'ye gönderilecek metin (önizlemeli)
    status        TEXT DEFAULT 'queued',     -- queued|sent|skipped|failed
    delivery_method TEXT DEFAULT 'wp',       -- wp|web|email
    wp_active_at_queue BOOL DEFAULT FALSE,   -- queue anındaki flag durumu
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    sent_at       TIMESTAMPTZ,
    skip_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tbq_scheduled ON teacher_briefing_queue(scheduled_for, status);
CREATE INDEX IF NOT EXISTS idx_tbq_teacher ON teacher_briefing_queue(teacher_phone, scheduled_for DESC);

-- ─── F2: Auto Follow-Up Engine ───────────────────────────────────────────
-- Sınav sync sonrası her öğrenci için pedagojik öneri üretimi.
-- Trigger: post_sync_update.py veya manuel.
CREATE TABLE IF NOT EXISTS student_followups (
    id              SERIAL PRIMARY KEY,
    soz_no          INTEGER NOT NULL,
    student_name    TEXT,
    trigger_event   TEXT NOT NULL,           -- 'exam_sync'|'topic_weak'|'attendance_drop'|'manual'
    trigger_ref     TEXT,                    -- exam_code, topic_name vs.
    weak_topics     JSONB,                   -- [{ders, konu, hata_orani}, ...]
    suggestion_text TEXT,                    -- Cerebras ile üretilen pedagojik öneri (kısa, motive)
    suggested_resources JSONB,               -- [{type:'rag'|'video'|'soru', ref:'...', label:'...'}]
    suggested_etut  JSONB,                   -- {teacher_pref:..., date:..., topic:...}
    priority        TEXT DEFAULT 'normal',   -- low|normal|high|urgent
    status          TEXT DEFAULT 'queued',   -- queued|sent|seen|done|skipped
    delivery_method TEXT DEFAULT 'wp',
    wp_active_at_queue BOOL DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    sent_at         TIMESTAMPTZ,
    seen_at         TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ              -- 7 gün sonra auto-expire
);
CREATE INDEX IF NOT EXISTS idx_sf_soz_status ON student_followups(soz_no, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sf_priority ON student_followups(priority, status);

-- ─── F3: TTS Audio Cache ─────────────────────────────────────────────────
-- Ses dosyaları cache (aynı metin tekrar üretilmesin).
CREATE TABLE IF NOT EXISTS tts_audio_cache (
    id            SERIAL PRIMARY KEY,
    text_hash     TEXT NOT NULL UNIQUE,      -- SHA256 metin
    text_preview  TEXT,                       -- ilk 200 char (debug için)
    voice_model   TEXT NOT NULL,              -- 'tts-1' / 'tts-1-hd'
    voice_id      TEXT NOT NULL,              -- 'alloy'|'echo'|'fable'|'onyx'|'nova'|'shimmer'
    audio_url     TEXT,                       -- /static/tts/{hash}.mp3 veya CDN
    audio_path    TEXT,                       -- VPS'te dosya yolu
    duration_ms   INTEGER,
    size_bytes    INTEGER,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ DEFAULT NOW(),
    use_count     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tts_hash ON tts_audio_cache(text_hash);
CREATE INDEX IF NOT EXISTS idx_tts_used ON tts_audio_cache(last_used_at DESC);

-- ─── F4: Conditional Assignments — student_todo extension ──────────────
-- Mevcut student_todo tablosuna deadline + escalation kolonları ekle.
-- (Tablo yoksa oluştur, varsa ALTER ile genişlet.)
CREATE TABLE IF NOT EXISTS student_todo (
    id              SERIAL PRIMARY KEY,
    soz_no          INTEGER NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    assigned_by     TEXT,                    -- 'teacher_xx' / 'rehber_xx' / 'self'
    assigned_phone  TEXT,                    -- atayan kişinin phone'u (notif için)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          TEXT DEFAULT 'open'      -- open|done|skipped|expired
);

-- Yeni kolonlar (idempotent)
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS deadline TIMESTAMPTZ;
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS reminder_at TIMESTAMPTZ;     -- deadline-2gün
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ;    -- deadline geçti, atayan haberdar
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS escalation_target TEXT;      -- 'teacher'|'rehber'|'veli'
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS topic_ref TEXT;              -- ilişkili konu
ALTER TABLE student_todo ADD COLUMN IF NOT EXISTS resource_links JSONB;        -- [{type, ref, label}]

CREATE INDEX IF NOT EXISTS idx_todo_deadline ON student_todo(deadline, status)
    WHERE status = 'open' AND deadline IS NOT NULL;

-- Eskalasyon kuyruğu (WP gated)
CREATE TABLE IF NOT EXISTS todo_escalation_queue (
    id            SERIAL PRIMARY KEY,
    todo_id       INTEGER REFERENCES student_todo(id) ON DELETE CASCADE,
    soz_no        INTEGER,
    student_name  TEXT,
    target_role   TEXT,                      -- 'teacher'|'rehber'|'veli'|'admin'
    target_phone  TEXT,
    target_name   TEXT,
    escalation_type TEXT,                    -- 'reminder_2d'|'deadline_passed'|'never_started'
    payload       JSONB,
    status        TEXT DEFAULT 'queued',
    wp_active_at_queue BOOL DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    sent_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_teq_status ON todo_escalation_queue(status, created_at);

-- ─── F5: Predicted Grade Cache ───────────────────────────────────────────
-- Çalışmam panel daily brief'e hızlı okuma için cache.
-- predictive_model.py'den günlük yenilenir (gece cron).
CREATE TABLE IF NOT EXISTS predicted_grade_cache (
    soz_no              INTEGER PRIMARY KEY,
    student_name        TEXT,
    sinav_turu          TEXT,                -- 'TYT'|'AYT'
    last_3_avg_net      NUMERIC(6,2),
    predicted_score     NUMERIC(7,2),        -- 0-560 arası YKS puan tahmin
    confidence          NUMERIC(3,2),        -- 0-1
    trend_direction     TEXT,                -- 'up'|'flat'|'down'
    trend_magnitude     NUMERIC(5,2),        -- son 3 vs önceki 3 fark
    target_score        NUMERIC(7,2),        -- öğrencinin hedef puanı (varsa)
    gap_to_target       NUMERIC(7,2),
    bottleneck_topics   JSONB,               -- [{ders, konu, neta_etki}]
    monthly_uplift_needed NUMERIC(5,2),      -- ayda kaç net artış gerek
    last_computed       TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ          -- 24 saat sonra refresh
);
CREATE INDEX IF NOT EXISTS idx_pgc_expires ON predicted_grade_cache(expires_at);

-- ─── ORTAK: WP Delivery Master Switch (sistem ayarı) ────────────────────
-- Tek noktadan kontrol — Neo "aktif" diyene kadar False kalır.
INSERT INTO sistem_ayar (anahtar, deger, aciklama, updated_at)
VALUES
    ('TEACHER_BRIEFING_WP_ACTIVE', 'false', 'F1 öğretmen brief WP gönderim — yeni sezon (1 Eyl)', NOW()),
    ('FOLLOWUP_WP_ACTIVE',         'false', 'F2 follow-up WP gönderim — yeni sezon', NOW()),
    ('TTS_WP_ACTIVE',              'false', 'F3 TTS WP voice mesaj — yeni sezon', NOW()),
    ('TODO_ESCALATION_WP_ACTIVE',  'false', 'F4 to-do eskalasyon WP — yeni sezon', NOW()),
    ('NEW_FEATURES_DRY_RUN',       'true',  'Tüm yeni F1-F5 modüllerinde DRY RUN modu', NOW())
ON CONFLICT (anahtar) DO NOTHING;
