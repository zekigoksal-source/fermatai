-- Self-Dev Pipeline Schema (Oturum 25.29 — Evre 1)
-- ====================================================
-- Bot kendi kodunu OKUYAbilir, BRIEF yazabilir. Yazma henuz YOK.
-- Kill switch: sistem_ayar.SELF_DEV_PIPELINE_ACTIVE

SET search_path TO fermat, public;

-- Brief writer outputlari: konusmadan turetilmis fix onerileri
CREATE TABLE IF NOT EXISTS self_dev_briefs (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMP DEFAULT NOW(),
    conversation_id TEXT,
    triggered_by    TEXT,
    title           TEXT NOT NULL,
    problem_summary TEXT,
    files_touched   TEXT[],
    proposed_diff   TEXT,
    risk_level      TEXT DEFAULT 'unknown',
    status          TEXT DEFAULT 'draft',
    applied_commit  TEXT,
    applied_at      TIMESTAMP,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_brief_status ON self_dev_briefs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brief_phone ON self_dev_briefs(triggered_by, created_at DESC);

-- Audit log: her self-dev fonksiyon cagrisi (read dahil)
CREATE TABLE IF NOT EXISTS self_dev_audit (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMP DEFAULT NOW(),
    actor_phone TEXT,
    tool_name   TEXT,
    args_jsonb  JSONB,
    success     BOOLEAN,
    bytes_read  INTEGER,
    error_msg   TEXT,
    blocked_by  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_phone_date ON self_dev_audit(actor_phone, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON self_dev_audit(tool_name, created_at DESC);

-- Kill switch
INSERT INTO sistem_ayar (key, value, aciklama)
VALUES ('SELF_DEV_PIPELINE_ACTIVE', 'true', 'Evre 1 read+brief — Neo aciksa true, kapaliysa false')
ON CONFLICT (key) DO NOTHING;
