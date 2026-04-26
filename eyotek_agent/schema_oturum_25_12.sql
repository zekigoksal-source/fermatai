-- ============================================================
-- Oturum 25.12 — Öğrenci Günlük Takip Sistemi (GRAFEN'a benzer)
-- ============================================================
-- 7 modül: Günlük Program + To Do + Alışkanlık + Sınav/Ödev +
-- Çalışma İstatistik + Fiziksel Aktivite + Bugünkü Notum
--
-- Tüm tablolar IF NOT EXISTS — idempotent.
-- KVKK: phone/soz_no'ya göre ACL — öğrenci sadece kendi verisini görür.
-- ============================================================

-- 1. GÜNLÜK PROGRAM — saatli ders/aktivite blokları
CREATE TABLE IF NOT EXISTS student_daily_program (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    plan_date DATE NOT NULL DEFAULT CURRENT_DATE,
    start_time TIME NOT NULL,
    end_time TIME,
    title TEXT NOT NULL,                -- "AYT Matematik 35. Video"
    ders TEXT,                          -- "Matematik" (opsiyonel)
    konu TEXT,                          -- "Türev Uygulamaları" (opsiyonel)
    completed BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dp_soz_date ON student_daily_program(soz_no, plan_date DESC);
CREATE INDEX IF NOT EXISTS idx_dp_completed ON student_daily_program(soz_no, completed)
    WHERE completed = FALSE;

-- 2. TO DO LIST — yapılacaklar (tarih bağımlı veya genel)
CREATE TABLE IF NOT EXISTS student_todo (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    title TEXT NOT NULL,                -- "Kimya ödevi"
    due_date DATE,                      -- opsiyonel deadline
    priority TEXT DEFAULT 'normal',     -- 'low'|'normal'|'high'|'urgent'
    completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_todo_soz_open ON student_todo(soz_no, completed)
    WHERE completed = FALSE;

-- 3. ALIŞKANLIK TAKİBİ — günlük tekrarlanan rutinler (egzersiz, paragraf okuma vs)
CREATE TABLE IF NOT EXISTS student_habits (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    habit_name TEXT NOT NULL,           -- "30 dk paragraf soru çözümü"
    target_days TEXT[],                 -- ['Pzt','Sal','Çar','Per','Cum','Cmt','Paz']
    streak INT DEFAULT 0,                -- ardışık başarı serisi
    longest_streak INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_habit_soz_active ON student_habits(soz_no, is_active);

-- Alışkanlık günlük log
CREATE TABLE IF NOT EXISTS student_habit_log (
    id SERIAL PRIMARY KEY,
    habit_id INT NOT NULL REFERENCES student_habits(id) ON DELETE CASCADE,
    log_date DATE NOT NULL DEFAULT CURRENT_DATE,
    completed BOOLEAN DEFAULT TRUE,
    note TEXT,
    UNIQUE(habit_id, log_date)
);
CREATE INDEX IF NOT EXISTS idx_habitlog_date ON student_habit_log(habit_id, log_date DESC);

-- 4. SINAV/ÖDEV TAKVİMİ — yaklaşan deneme + ödev tarihleri
CREATE TABLE IF NOT EXISTS student_exam_calendar (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    title TEXT NOT NULL,                 -- "1 Haziran Matematik Denemesi"
    event_type TEXT DEFAULT 'sinav',     -- 'sinav'|'odev'|'etut'|'rehberlik'
    event_date DATE NOT NULL,
    event_time TIME,
    ders TEXT,
    completed BOOLEAN DEFAULT FALSE,
    score TEXT,                          -- "65 net" (sınav sonrası)
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_examcal_soz_date ON student_exam_calendar(soz_no, event_date);

-- 5. ÇALIŞMA İSTATİSTİKLERİ — günlük süre + soru sayısı
CREATE TABLE IF NOT EXISTS student_study_stats (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    log_date DATE NOT NULL DEFAULT CURRENT_DATE,
    total_minutes INT DEFAULT 0,         -- Toplam çalışma süresi (dk)
    questions_solved INT DEFAULT 0,      -- Çözülen soru sayısı
    ders_breakdown JSONB,                -- {"Matematik": 60, "Fizik": 30, ...}
    konu_breakdown JSONB,                -- {"Türev": 25, "Limit": 35, ...}
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(soz_no, log_date)             -- Her gün için tek kayıt (UPDATE ile artır)
);
CREATE INDEX IF NOT EXISTS idx_stats_soz_date ON student_study_stats(soz_no, log_date DESC);

-- 6. FİZİKSEL AKTİVİTE — egzersiz/yürüyüş/spor
CREATE TABLE IF NOT EXISTS student_physical_activity (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    log_date DATE NOT NULL DEFAULT CURRENT_DATE,
    activity_type TEXT,                  -- 'koşu'|'yürüyüş'|'fitness'|'futbol'|'serbest'
    duration_minutes INT,                -- süre (dk)
    intensity TEXT,                      -- 'düşük'|'orta'|'yüksek'
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pa_soz_date ON student_physical_activity(soz_no, log_date DESC);

-- 7. BUGÜNKÜ NOTUM — günlük serbest not / mood
CREATE TABLE IF NOT EXISTS student_daily_notes (
    id SERIAL PRIMARY KEY,
    soz_no INT NOT NULL,
    log_date DATE NOT NULL DEFAULT CURRENT_DATE,
    note TEXT NOT NULL,
    mood TEXT,                           -- 'verimli'|'normal'|'yorgun'|'stresli'|'motiveli'
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(soz_no, log_date)             -- Her gün tek not (UPDATE ile değiştir)
);
CREATE INDEX IF NOT EXISTS idx_notes_soz_date ON student_daily_notes(soz_no, log_date DESC);

-- ── METADATA ──
INSERT INTO schema_migrations (version, description)
VALUES ('25.12', 'Ogrenci gunluk takip — GRAFEN-tarzi 7 modul')
ON CONFLICT (version) DO NOTHING;

-- COMPLETE
SELECT 'Schema 25.12 applied. New tables count:' AS result, COUNT(*)
FROM pg_tables WHERE schemaname='public' AND tablename IN (
    'student_daily_program', 'student_todo', 'student_habits',
    'student_habit_log', 'student_exam_calendar', 'student_study_stats',
    'student_physical_activity', 'student_daily_notes'
);
