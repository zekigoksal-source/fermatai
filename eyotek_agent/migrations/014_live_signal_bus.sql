-- Live Signal Bus — Kapı 6 (Oturum 25.29 — Brief #4)
-- =====================================================
-- Sistem retrospektif öz-gözlemden ANLIK introspeksyona geçiyor.
-- Her token/adım üretilirken sinyal yayar, TTL=5dk olan kayıtlara persist eder.
-- Subscriber'lar (ör: FermatCoreAgentV2) anlık dinleyerek müdahale edebilir.

SET search_path TO fermat, public;

CREATE TABLE IF NOT EXISTS live_signals (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,           -- pre_route, post_route, crisis_signal, quality_feedback, token_emit, context_check
    payload     JSONB,                    -- esnek veri (route adı, frustration sinyali, RAG hit kalitesi, vs)
    actor_phone TEXT,                     -- hangi kullanıcı tetikledi (sadece Neo Kapı 6 evresinde)
    consumed    BOOLEAN DEFAULT FALSE,    -- subscriber tüketti mi (audit + flush_expired için)
    consumed_at TIMESTAMP
);

-- Subscriber pull eder, bu yüzden hızlı "yeni sinyal" sorgu için index
CREATE INDEX IF NOT EXISTS idx_live_signals_type_unconsumed
    ON live_signals(signal_type, consumed) WHERE consumed = FALSE;

-- TTL flush için
CREATE INDEX IF NOT EXISTS idx_live_signals_expires
    ON live_signals(expires_at) WHERE consumed = FALSE;

-- Aktör bazlı debug (Neo'nun trafiği gözle, kalan kullanıcılar v1'de)
CREATE INDEX IF NOT EXISTS idx_live_signals_actor
    ON live_signals(actor_phone, created_at DESC);
