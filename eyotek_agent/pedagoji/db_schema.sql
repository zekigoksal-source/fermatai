-- Pedagoji V2 — DB Schema (25.41 Neo)
-- =====================================
-- 8 kategori bazlı anekdot + kavram tabloları
-- Eski tablolar (anekdotlar, pedagoji_literatur) korunsun (geriye uyum).
-- Yeni: pedagoji_kategori, pedagoji_kavram_v2, pedagoji_anekdot_v2

-- ─── KATEGORI ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pedagoji_kategori (
    slug TEXT PRIMARY KEY,
    baslik TEXT NOT NULL,
    aciklama TEXT,
    trigger_patterns TEXT,
    keyword_boost TEXT,
    oneri_formul TEXT,
    default_konum TEXT
);

-- ─── KAVRAM v2 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pedagoji_kavram_v2 (
    slug TEXT PRIMARY KEY,
    baslik TEXT NOT NULL,
    kategori TEXT REFERENCES pedagoji_kategori(slug),
    kisaca TEXT,
    aciklama TEXT,
    kullanim_ornegi TEXT,
    trigger_patterns TEXT,
    kaynak TEXT,
    etiketler TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_kavram_kategori ON pedagoji_kavram_v2(kategori);
CREATE INDEX IF NOT EXISTS idx_kavram_etiketler ON pedagoji_kavram_v2 USING gin(to_tsvector('simple', etiketler));

-- ─── ANEKDOT v2 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pedagoji_anekdot_v2 (
    slug TEXT PRIMARY KEY,
    kim TEXT NOT NULL,
    kategori TEXT REFERENCES pedagoji_kategori(slug),
    konu TEXT,
    baslik TEXT,
    metin TEXT NOT NULL,
    ders TEXT,
    duygusal_hedef TEXT,
    kaynak TEXT,
    etiketler TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_anekdot_kategori ON pedagoji_anekdot_v2(kategori);
CREATE INDEX IF NOT EXISTS idx_anekdot_duygusal ON pedagoji_anekdot_v2(duygusal_hedef);
CREATE INDEX IF NOT EXISTS idx_anekdot_etiketler ON pedagoji_anekdot_v2 USING gin(to_tsvector('simple', etiketler));

-- ─── KULLANIM LOG (öğrenme — hangi paket en çok işe yaradı) ──
CREATE TABLE IF NOT EXISTS pedagoji_kullanim_log (
    id SERIAL PRIMARY KEY,
    kategori TEXT,
    kavram_slug TEXT,
    anekdot_slug TEXT,
    soz_no TEXT,
    mesaj_excerpt TEXT,  -- ilk 100 char
    trigger_kelime TEXT,  -- match olan kelime
    olcum TEXT,  -- 'auto_match', 'tool_call', 'manual'
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_log_kategori ON pedagoji_kullanim_log(kategori);
CREATE INDEX IF NOT EXISTS idx_log_soz ON pedagoji_kullanim_log(soz_no);
CREATE INDEX IF NOT EXISTS idx_log_date ON pedagoji_kullanim_log(created_at DESC);
