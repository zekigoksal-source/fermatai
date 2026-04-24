# ═══════════════════════════════════════════════════════
#  Fermat AI — Windows PowerShell Kurulum Scripti
#  Çalıştır: cd FermatAI dizinindeyken: .\setup_windows.ps1
# ═══════════════════════════════════════════════════════

Write-Host ""
Write-Host "  FERMAT AI — Dizin Yapısı Kuruluyor" -ForegroundColor Cyan
Write-Host ""

# ── Dizinleri oluştur ────────────────────────────────────────────────────
$dirs = @(
    "infra\init_sql",
    "eyotek_agent",
    "llm_tools",
    "n8n_workflows",
    "docs"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Write-Host "  [+] $d" -ForegroundColor Green
}

# ── infra\.env ───────────────────────────────────────────────────────────
$infraEnv = @"
# PostgreSQL
POSTGRES_PASSWORD=guclu_bir_sifre_yaz

# ChromaDB token
CHROMA_TOKEN=chroma_token_degistir

# Redis
REDIS_PASSWORD=redis_sifre_degistir

# n8n
N8N_ENCRYPTION_KEY=en_az_32_karakter_rastgele_key_yaz
N8N_USER=admin
N8N_PASSWORD=n8n_admin_sifren

# Ollama (WSL2 icinde kosuyor)
OLLAMA_BASE_URL=http://host.docker.internal:11434

# Claude API (hibrit kullanim icin)
ANTHROPIC_API_KEY=PLACEHOLDER_API_KEY_HERE
"@
$infraEnv | Out-File -FilePath "infra\.env" -Encoding UTF8
Write-Host "  [+] infra\.env olusturuldu" -ForegroundColor Green

# ── eyotek_agent\.env ────────────────────────────────────────────────────
$agentEnv = @"
EYOTEK_URL=https://fermat.eyotek.com/v1
EYOTEK_USER=1003zeki
EYOTEK_PASS=buraya_yeni_sifren_yaz

HEADLESS=true
SESSION_FILE=.eyotek_session.json

DATABASE_URL=postgresql://fermat:guclu_bir_sifre_yaz@localhost:5432/fermatai
"@
$agentEnv | Out-File -FilePath "eyotek_agent\.env" -Encoding UTF8
Write-Host "  [+] eyotek_agent\.env olusturuldu" -ForegroundColor Green

# ── infra\docker-compose.yml ─────────────────────────────────────────────
$dockerCompose = @"
version: "3.9"

networks:
  fermat_net:
    driver: bridge

volumes:
  postgres_data:
  chromadb_data:
  n8n_data:
  redis_data:

services:

  postgres:
    image: postgres:16-alpine
    container_name: fermat_postgres
    restart: unless-stopped
    networks:
      - fermat_net
    environment:
      POSTGRES_DB: fermatai
      POSTGRES_USER: fermat
      POSTGRES_PASSWORD: `${POSTGRES_PASSWORD:-fermat_secret_2024}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init_sql:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fermat -d fermatai"]
      interval: 10s
      timeout: 5s
      retries: 5

  chromadb:
    image: chromadb/chroma:latest
    container_name: fermat_chroma
    restart: unless-stopped
    networks:
      - fermat_net
    environment:
      ANONYMIZED_TELEMETRY: "false"
      ALLOW_RESET: "true"
    volumes:
      - chromadb_data:/chroma/chroma
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/api/v1/heartbeat || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 3

  redis:
    image: redis:7-alpine
    container_name: fermat_redis
    restart: unless-stopped
    networks:
      - fermat_net
    command: redis-server --requirepass `${REDIS_PASSWORD:-fermat_redis_2024} --maxmemory 4gb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "`${REDIS_PASSWORD:-fermat_redis_2024}", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

  n8n:
    image: n8nio/n8n:latest
    container_name: fermat_n8n
    restart: unless-stopped
    networks:
      - fermat_net
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_PORT: 5432
      DB_POSTGRESDB_DATABASE: fermatai
      DB_POSTGRESDB_USER: fermat
      DB_POSTGRESDB_PASSWORD: `${POSTGRES_PASSWORD:-fermat_secret_2024}
      DB_POSTGRESDB_SCHEMA: n8n
      EXECUTIONS_MODE: queue
      QUEUE_BULL_REDIS_HOST: redis
      QUEUE_BULL_REDIS_PORT: 6379
      QUEUE_BULL_REDIS_PASSWORD: `${REDIS_PASSWORD:-fermat_redis_2024}
      N8N_HOST: 0.0.0.0
      N8N_PORT: 5678
      WEBHOOK_URL: http://localhost:5678
      N8N_ENCRYPTION_KEY: `${N8N_ENCRYPTION_KEY:-fermat_n8n_key_change_in_prod}
      GENERIC_TIMEZONE: Europe/Istanbul
      TZ: Europe/Istanbul
      N8N_LOG_LEVEL: info
      N8N_BASIC_AUTH_ACTIVE: "true"
      N8N_BASIC_AUTH_USER: `${N8N_USER:-admin}
      N8N_BASIC_AUTH_PASSWORD: `${N8N_PASSWORD:-fermat2024}
    volumes:
      - n8n_data:/home/node/.n8n
    ports:
      - "5678:5678"

  n8n_worker:
    image: n8nio/n8n:latest
    container_name: fermat_n8n_worker
    restart: unless-stopped
    networks:
      - fermat_net
    depends_on:
      - n8n
    command: worker
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: postgres
      DB_POSTGRESDB_PORT: 5432
      DB_POSTGRESDB_DATABASE: fermatai
      DB_POSTGRESDB_USER: fermat
      DB_POSTGRESDB_PASSWORD: `${POSTGRES_PASSWORD:-fermat_secret_2024}
      DB_POSTGRESDB_SCHEMA: n8n
      EXECUTIONS_MODE: queue
      QUEUE_BULL_REDIS_HOST: redis
      QUEUE_BULL_REDIS_PORT: 6379
      QUEUE_BULL_REDIS_PASSWORD: `${REDIS_PASSWORD:-fermat_redis_2024}
      N8N_ENCRYPTION_KEY: `${N8N_ENCRYPTION_KEY:-fermat_n8n_key_change_in_prod}
      GENERIC_TIMEZONE: Europe/Istanbul
    volumes:
      - n8n_data:/home/node/.n8n
"@
$dockerCompose | Out-File -FilePath "infra\docker-compose.yml" -Encoding UTF8
Write-Host "  [+] infra\docker-compose.yml olusturuldu" -ForegroundColor Green

# ── infra\init_sql\01_schema.sql ─────────────────────────────────────────
$sql = @"
CREATE SCHEMA IF NOT EXISTS n8n;
CREATE SCHEMA IF NOT EXISTS fermat;
SET search_path TO fermat;

CREATE TABLE IF NOT EXISTS students (
    id              SERIAL PRIMARY KEY,
    eyotek_id       VARCHAR(50) UNIQUE NOT NULL,
    full_name       VARCHAR(200) NOT NULL,
    class_name      VARCHAR(50),
    phone           VARCHAR(20),
    parent_phone    VARCHAR(20),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS academic_snapshots (
    id          SERIAL PRIMARY KEY,
    student_id  INTEGER REFERENCES students(id),
    exam_name   VARCHAR(200),
    exam_date   DATE,
    exam_type   VARCHAR(20),
    subject     VARCHAR(100),
    correct     NUMERIC(5,2),
    wrong       NUMERIC(5,2),
    net         NUMERIC(6,2),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pedagogical_signals (
    id              SERIAL PRIMARY KEY,
    student_id      INTEGER REFERENCES students(id),
    signal_type     VARCHAR(50),
    severity        SMALLINT CHECK (severity BETWEEN 1 AND 5),
    source          VARCHAR(50),
    raw_text        TEXT,
    structured_data JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS etut_plans (
    id             SERIAL PRIMARY KEY,
    student_id     INTEGER REFERENCES students(id),
    teacher_id     VARCHAR(50),
    subject        VARCHAR(100),
    planned_date   DATE,
    duration_min   INTEGER DEFAULT 60,
    status         VARCHAR(20) DEFAULT 'planned',
    eyotek_written BOOLEAN DEFAULT FALSE,
    notes          TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              SERIAL PRIMARY KEY,
    student_id      INTEGER REFERENCES students(id),
    session_start   TIMESTAMPTZ DEFAULT NOW(),
    session_end     TIMESTAMPTZ,
    message_count   INTEGER DEFAULT 0,
    extracted_flags JSONB,
    summary         TEXT
);

CREATE TABLE IF NOT EXISTS attendance_log (
    id          SERIAL PRIMARY KEY,
    student_id  INTEGER REFERENCES students(id),
    class_date  DATE,
    lesson      VARCHAR(100),
    status      VARCHAR(20),
    synced_from VARCHAR(20) DEFAULT 'eyotek',
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teacher_performance (
    id                SERIAL PRIMARY KEY,
    teacher_eyotek_id VARCHAR(50),
    teacher_name      VARCHAR(200),
    subject           VARCHAR(100),
    class_name        VARCHAR(50),
    period_start      DATE,
    period_end        DATE,
    avg_net_before    NUMERIC(6,2),
    avg_net_after     NUMERIC(6,2),
    net_delta         NUMERIC(6,2),
    hw_count          INTEGER DEFAULT 0,
    recorded_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS escalations (
    id              SERIAL PRIMARY KEY,
    student_id      INTEGER REFERENCES students(id),
    risk_level      VARCHAR(20),
    trigger_reason  TEXT,
    notified_roles  TEXT[],
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_student   ON academic_snapshots(student_id, exam_date);
CREATE INDEX IF NOT EXISTS idx_signals_student     ON pedagogical_signals(student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_etut_student        ON etut_plans(student_id, planned_date);
CREATE INDEX IF NOT EXISTS idx_attendance_student  ON attendance_log(student_id, class_date);
CREATE INDEX IF NOT EXISTS idx_escalations_student ON escalations(student_id, created_at);
"@
$sql | Out-File -FilePath "infra\init_sql\01_schema.sql" -Encoding UTF8
Write-Host "  [+] infra\init_sql\01_schema.sql olusturuldu" -ForegroundColor Green

# ── .gitignore ───────────────────────────────────────────────────────────
$gitignore = @"
.env
*.env
.eyotek_session.json
__pycache__/
*.pyc
.venv/
node_modules/
*.log
"@
$gitignore | Out-File -FilePath ".gitignore" -Encoding UTF8
Write-Host "  [+] .gitignore olusturuldu" -ForegroundColor Green

Write-Host ""
Write-Host "  Tum dosyalar olusturuldu!" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Simdi yapman gerekenler:" -ForegroundColor Yellow
Write-Host "  1. infra\.env dosyasini ac, sifreleri degistir"
Write-Host "  2. eyotek_agent\.env dosyasinda EYOTEK_PASS satirini guncelle"
Write-Host "  3. cd infra && docker compose up -d"
Write-Host ""
