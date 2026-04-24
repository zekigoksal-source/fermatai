#!/bin/bash
# ===================================================
# FermatAI VPS — First Install v2 (fail2ban OFF)
# fail2ban kaldırıldı — self-lock riski çok yüksek kurulum sırasında
# UFW + SSH key-only auth yeterli güvenlik
# ===================================================
set -euo pipefail
trap 'echo "[ERROR] Satır $LINENO: $BASH_COMMAND" >&2' ERR

R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
log()  { echo -e "${B}[$(date +%H:%M:%S)]${N} $*"; }
ok()   { echo -e "${G}[OK]${N} $*"; }
warn() { echo -e "${Y}[WARN]${N} $*"; }
err()  { echo -e "${R}[ERR]${N} $*" >&2; }

if [[ $EUID -ne 0 ]]; then
    err "Root olarak çalıştır"
    exit 1
fi

log "FermatAI VPS kurulum v2 başlıyor (fail2ban YOK)..."

# ─── 1. Sistem güncellemeleri ──────────────────────
log "1/9 — Sistem güncelleniyor..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git vim htop iotop \
    software-properties-common apt-transport-https ca-certificates gnupg \
    build-essential pkg-config unattended-upgrades
ok "Sistem güncel"

# ─── 2. Kullanıcı 'neo' ──────────────────────────
log "2/9 — Kullanıcı 'neo'..."
if ! id neo &>/dev/null; then
    useradd -m -s /bin/bash neo
    usermod -aG sudo neo
    mkdir -p /home/neo/.ssh
    [ -f /root/.ssh/authorized_keys ] && cp /root/.ssh/authorized_keys /home/neo/.ssh/
    chown -R neo:neo /home/neo/.ssh
    chmod 700 /home/neo/.ssh
    chmod 600 /home/neo/.ssh/authorized_keys 2>/dev/null || true
    # Sudo şifresiz (scripted deploy için)
    echo "neo ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-neo
    chmod 440 /etc/sudoers.d/90-neo
    ok "neo hazır (sudo NOPASSWD)"
else
    warn "neo zaten var"
fi

# ─── 3. UFW firewall ─────────────────────────────
log "3/9 — UFW firewall..."
apt-get install -y -qq ufw
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ok "UFW aktif: 22, 80, 443"

# ─── 4. Docker ─────────────────────────────────
log "4/9 — Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    usermod -aG docker neo
    systemctl enable --now docker
    ok "Docker kuruldu"
else
    warn "Docker zaten var"
fi

# ─── 5. Python 3.11 ─────────────────────────────
log "5/9 — Python 3.11..."
apt-get install -y -qq python3.12 python3.12-venv python3.12-dev python3-pip
ok "Python: $(python3.12 --version)"

# ─── 6. PostgreSQL + Redis (Docker) ─────────────
log "6/9 — PostgreSQL + pgvector + Redis..."
mkdir -p /opt/postgres-data /opt/redis-data

if [ ! -f /opt/.postgres_password ]; then
    PG_PASS=$(openssl rand -base64 24 | tr -d '/+=')
    echo "POSTGRES_PASSWORD=$PG_PASS" > /opt/.postgres_password
    chmod 600 /opt/.postgres_password
    ok "PostgreSQL şifre: /opt/.postgres_password"
fi
source /opt/.postgres_password

cat > /opt/docker-compose.yml << EOF
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: fermat_postgres
    restart: unless-stopped
    ports:
      - "127.0.0.1:5432:5432"
    environment:
      POSTGRES_DB: fermatai
      POSTGRES_USER: fermat
      POSTGRES_PASSWORD: $POSTGRES_PASSWORD
    volumes:
      - /opt/postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fermat -d fermatai"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: fermat_redis
    restart: unless-stopped
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - /opt/redis-data:/data
    command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
EOF

cd /opt && docker compose up -d
sleep 10
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || warn "pgvector henüz hazır değil"
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS unaccent;" 2>/dev/null || true
ok "PostgreSQL + Redis ayakta"

# ─── 7. nginx + certbot ─────────────────────────
log "7/9 — nginx + certbot..."
apt-get install -y -qq nginx certbot python3-certbot-nginx
systemctl enable --now nginx
ok "nginx: $(nginx -v 2>&1)"

# ─── 8. Playwright + Chromium deps ──────────────
log "8/9 — Playwright Chrome bağımlılıkları..."
apt-get install -y -qq \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2t64 libdrm2 libxss1 libxtst6 \
    fonts-liberation xvfb
ok "Playwright deps kuruldu"

# ─── 9. FermatAI dizinleri ──────────────────────
log "9/9 — Dizinler..."
mkdir -p /opt/fermatai /opt/backups/fermatai /var/log/fermatai
chown -R neo:neo /opt/fermatai /opt/backups /var/log/fermatai
ok "Dizinler hazır"

# ─── Otomatik security update ──────────────────
dpkg-reconfigure --priority=low unattended-upgrades -fnoninteractive 2>/dev/null || true

# ─── SSH hardening — EN SON, başka deneme yok ──
log "FINAL — SSH hardening (sadece key, root kapalı)..."
sed -i 's/^#*PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PubkeyAuthentication .*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl reload ssh
ok "SSH hardened"

echo ""
echo "============================================"
echo -e "${G}VPS kurulumu v2 TAMAMLANDI${N}"
echo "============================================"
echo "IP: $(curl -s ifconfig.me || echo '?')"
echo "PostgreSQL şifresi: /opt/.postgres_password"
echo "Sonraki: neo@$IP olarak SSH ile bağlan"
echo "============================================"
