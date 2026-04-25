-- ============================================================
-- Oturum 25.9 — Mega Genisleme Schema
-- ============================================================
-- 5 buyuk yeni ozellik icin tablolar:
--   1. Adaptive Intelligence (ELO + SM-2 + Misconception)
--   2. Predictive Performance Model (YKS puan tahmin)
--   3. Notifications (Dashboard bildirim merkezi)
--   4. Self-Improving Prompts (Atlas-2)
--   5. Knowledge Graph (Concept network)
--
-- TUMU YENI TABLO — varolanlari BOZMAZ.
-- IF NOT EXISTS guard'li, idempotent — birkaç kez calistirilabilir.
-- ============================================================

-- ── 1. ADAPTIVE INTELLIGENCE ENGINE ──

-- ELO rating: her ogrenci × konu icin dinamik zorluk seviyesi
CREATE TABLE IF NOT EXISTS student_topic_elo (
    soz_no INT NOT NULL,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    rating INT DEFAULT 1200,         -- ELO başlangıç (chess standartı)
    games_played INT DEFAULT 0,      -- Toplam soru sayısı
    last_correct BOOLEAN,            -- Son cevap dogru mu
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (soz_no, ders, konu)
);
CREATE INDEX IF NOT EXISTS idx_elo_soz ON student_topic_elo(soz_no);
CREATE INDEX IF NOT EXISTS idx_elo_rating ON student_topic_elo(rating);

-- SM-2 spaced repetition: konu tekrar tarihleri
CREATE TABLE IF NOT EXISTS student_review_schedule (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    interval_days INT DEFAULT 1,      -- SM-2 algoritma: sonraki tekrar gunu
    ease_factor REAL DEFAULT 2.5,     -- SM-2 EF (1.3-2.5)
    repetitions INT DEFAULT 0,        -- Dogru cevap streak
    next_review_date DATE NOT NULL,
    last_quality INT,                 -- 0-5 son cevap kalitesi (SM-2 standartı)
    last_reviewed TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_review_due ON student_review_schedule(soz_no, next_review_date);
CREATE INDEX IF NOT EXISTS idx_review_topic ON student_review_schedule(soz_no, ders, konu);

-- Misconception graph: kavram yanılgıları
CREATE TABLE IF NOT EXISTS student_misconceptions (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    misconception TEXT NOT NULL,        -- "Integralın türevin tersi olduğunu unutuyor"
    confidence REAL DEFAULT 0.5,        -- 0-1 (her gözlemde artar)
    occurrence_count INT DEFAULT 1,
    sample_questions JSONB,             -- Hangi sorularda görüldü
    first_seen TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP DEFAULT NOW(),
    resolved BOOLEAN DEFAULT FALSE,     -- Cözüldü mü
    resolved_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_misc_soz ON student_misconceptions(soz_no, resolved);

-- ── 2. PREDICTIVE PERFORMANCE MODEL ──

-- Her ogrenci icin haftalik puan tahmini (snapshot)
CREATE TABLE IF NOT EXISTS student_predictions (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    prediction_date DATE NOT NULL DEFAULT CURRENT_DATE,
    predicted_tyt REAL,
    predicted_ayt REAL,
    predicted_yerlesme_puani REAL,
    confidence REAL,                    -- Model güven skoru 0-1
    target_university TEXT,
    target_program TEXT,
    target_probability REAL,            -- Hedef tutturma olasılığı 0-1
    bottleneck_topics JSONB,            -- En kritik 3-5 konu
    suggested_focus TEXT,               -- "Matematik 8 saat/hafta artır"
    days_to_yks INT,
    model_version TEXT DEFAULT 'v1',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pred_soz_date ON student_predictions(soz_no, prediction_date DESC);

-- ── 3. NOTIFICATIONS (Dashboard) ──

-- Bildirim merkezi: Atlas, alarm, sistem mesajları paneline akar
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    severity TEXT NOT NULL,             -- 'critical'/'warning'/'info'/'success'
    category TEXT NOT NULL,             -- 'system'/'student'/'teacher'/'eyotek'/'atlas'/'duygu'
    title TEXT NOT NULL,
    body TEXT,
    related_soz_no INT,
    related_phone TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    is_dismissed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    read_at TIMESTAMP,
    dismissed_at TIMESTAMP,
    metadata JSONB,                     -- Ek veriler (link, action, vs)
    expires_at TIMESTAMP                -- Auto-dismiss için
);
CREATE INDEX IF NOT EXISTS idx_notif_unread ON notifications(is_read, is_dismissed, created_at DESC)
    WHERE is_read=FALSE AND is_dismissed=FALSE;
CREATE INDEX IF NOT EXISTS idx_notif_category ON notifications(category, created_at DESC);

-- ── 4. SELF-IMPROVING PROMPTS (Atlas-2) ──

-- Bot kendi konusmalarini analiz edip prompt iyilestirme onerisi
CREATE TABLE IF NOT EXISTS prompt_suggestions (
    id SERIAL PRIMARY KEY,
    suggestion_date DATE DEFAULT CURRENT_DATE,
    category TEXT NOT NULL,             -- 'bug'/'improvement'/'pattern'/'guvenlik'
    severity TEXT NOT NULL,             -- 'high'/'medium'/'low'
    title TEXT NOT NULL,
    description TEXT NOT NULL,          -- Atlas-2'nin önerisi (Groq 70B uretti)
    affected_pattern TEXT,              -- Mesaj örüntüsü (ör. "Selam+soru kombinasyon")
    sample_conversations JSONB,         -- Örnek konuşmalar (3-5 mesaj)
    suggested_prompt_change TEXT,       -- Konkre system_prompts.py değişikliği
    expected_impact TEXT,               -- "%X mesajda iyileşme bekleniyor"
    status TEXT DEFAULT 'pending',      -- 'pending'/'approved'/'rejected'/'applied'/'rolled_back'
    applied_at TIMESTAMP,
    applied_by TEXT,                    -- 'neo' / 'auto'
    rollback_sha TEXT,                  -- Eski git SHA
    ab_test_results JSONB,              -- {before_score: X, after_score: Y, sample_size: N}
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP,
    reviewer_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_promptsugg_pending ON prompt_suggestions(status, severity, created_at DESC)
    WHERE status='pending';

-- ── 5. KNOWLEDGE GRAPH (Concept Network) ──

-- Konu node'ları (örn. "Matematik / Türev / TYT")
CREATE TABLE IF NOT EXISTS concept_nodes (
    id SERIAL PRIMARY KEY,
    ders TEXT NOT NULL,
    konu TEXT NOT NULL,
    seviye TEXT NOT NULL,               -- 'TYT'/'AYT'/'LGS'
    description TEXT,
    UNIQUE(ders, konu, seviye)
);
CREATE INDEX IF NOT EXISTS idx_concept_ders ON concept_nodes(ders, seviye);

-- Konu ilişkileri (prerequisite, related, extends)
CREATE TABLE IF NOT EXISTS concept_edges (
    id SERIAL PRIMARY KEY,
    from_node_id INT NOT NULL REFERENCES concept_nodes(id) ON DELETE CASCADE,
    to_node_id INT NOT NULL REFERENCES concept_nodes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,        -- 'prerequisite'/'related'/'extends'/'application'
    strength REAL DEFAULT 0.5,          -- 0-1 ilişki gücü
    UNIQUE(from_node_id, to_node_id, relation_type)
);

-- Öğrenci × konu ustalık seviyesi (knowledge graph üzerinde)
CREATE TABLE IF NOT EXISTS student_concept_mastery (
    soz_no INT NOT NULL,
    node_id INT NOT NULL REFERENCES concept_nodes(id) ON DELETE CASCADE,
    mastery_level REAL DEFAULT 0,       -- 0-1
    sample_count INT DEFAULT 0,         -- Kaç gözlemden hesaplandı
    last_assessed TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (soz_no, node_id)
);
CREATE INDEX IF NOT EXISTS idx_mastery_soz ON student_concept_mastery(soz_no);

-- ── 6. METADATA — Schema versiyon takibi ──
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT NOW(),
    description TEXT
);
INSERT INTO schema_migrations (version, description)
VALUES ('25.9', 'Mega genisleme: ELO/SM-2/Misconception/Prediction/Notifications/Atlas-2/KnowledgeGraph')
ON CONFLICT (version) DO NOTHING;

-- ── COMPLETE ──
SELECT 'Schema 25.9 applied: ' || COUNT(*) || ' tables exist' AS result
FROM information_schema.tables WHERE table_schema='public'
AND table_name IN ('student_topic_elo','student_review_schedule','student_misconceptions',
                   'student_predictions','notifications','prompt_suggestions',
                   'concept_nodes','concept_edges','student_concept_mastery');
