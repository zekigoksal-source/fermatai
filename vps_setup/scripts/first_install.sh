#!/bin/bash
# ===================================================
# FermatAI VPS — First Install Script
# Ubuntu 24.04 LTS üzerinde tek seferlik kurulum
# ===================================================
# Kullanım:
#   1. VPS'e root olarak SSH
#   2. scp first_install.sh root@VPS:/tmp/
#   3. bash /tmp/first_install.sh
# ===================================================

set -euo pipefail   # hata olursa dur, undefined var kullanma
trap 'echo "[ERROR] Satır $LINENO: $BASH_COMMAND" >&2' ERR

# Renkler
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'
log()  { echo -e "${B}[$(date +%H:%M:%S)]${N} $*"; }
ok()   { echo -e "${G}[OK]${N} $*"; }
warn() { echo -e "${Y}[WARN]${N} $*"; }
err()  { echo -e "${R}[ERR]${N} $*" >&2; }

# ─── Doğrulama ──────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    err "Root olarak çalıştır: sudo bash first_install.sh"
    exit 1
fi

log "FermatAI VPS kurulum başlıyor..."
log "Sistem: $(lsb_release -ds 2>/dev/null || echo '?')"

# ─── 1. Sistem güncellemeleri ──────────────────────
log "1/10 — Sistem paketleri güncelleniyor..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git vim htop iotop \
    software-properties-common apt-transport-https ca-certificates gnupg \
    build-essential pkg-config \
    unattended-upgrades
ok "Sistem güncel"

# ─── 2. Kullanıcı 'neo' ──────────────────────────
log "2/10 — Kullanıcı 'neo' oluşturuluyor..."
if ! id neo &>/dev/null; then
    useradd -m -s /bin/bash neo
    usermod -aG sudo neo
    # SSH key'i root'tan kopyala (Neo ilk bu key ile bağlanıyor)
    mkdir -p /home/neo/.ssh
    [ -f /root/.ssh/authorized_keys ] && cp /root/.ssh/authorized_keys /home/neo/.ssh/
    chown -R neo:neo /home/neo/.ssh
    chmod 700 /home/neo/.ssh
    chmod 600 /home/neo/.ssh/authorized_keys 2>/dev/null || true
    ok "Kullanıcı 'neo' hazır"
else
    warn "Kullanıcı 'neo' zaten var, atlandı"
fi

# ─── 3. Firewall (UFW) ──────────────────────────
log "3/10 — UFW firewall kurulum..."
apt-get install -y -qq ufw
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP (Let''s Encrypt)'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable
ok "Firewall aktif: 22, 80, 443 açık"

# ─── 4. fail2ban (SSH brute force koruması) ──────
log "4/10 — fail2ban kurulum..."
apt-get install -y -qq fail2ban

# Admin IP whitelist (self-lock önleme).
# Öncelik sırası: 1) ADMIN_IP env var (manuel)  2) SSH_CLIENT (oturum)  3) who -u fallback
: "${ADMIN_IP:=${SSH_CLIENT%% *}}"
if [ -z "$ADMIN_IP" ]; then
    ADMIN_IP=$(who -u 2>/dev/null | awk 'NR==1{print $NF}' | tr -d '()' | head -1)
fi
log "    Admin IP (whitelist): ${ADMIN_IP:-BILINMIYOR}"

cat > /etc/fail2ban/jail.local << EOF
[DEFAULT]
# Self-lockout koruması — admin IP whitelist + lokal
ignoreip = 127.0.0.1/8 ::1 ${ADMIN_IP}

[sshd]
enabled = true
port = 22
maxretry = 5
bantime = 3600
findtime = 600
EOF

# In-memory state, sqlite'ta persist yok (restart sonrası temiz)
sed -i 's|^#*dbfile.*|dbfile = :memory:|' /etc/fail2ban/fail2ban.conf || true

systemctl enable --now fail2ban
ok "fail2ban aktif (whitelist: ${ADMIN_IP:-lokal}, in-memory state)"

# ─── 5. SSH sertleştirme ────────────────────────
log "5/10 — SSH config sertleştiriliyor..."
sed -i 's/^#*PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PubkeyAuthentication .*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
systemctl reload ssh
ok "SSH: sadece key ile login, root disabled"

# ─── 6. Docker ──────────────────────────────────
log "6/10 — Docker kurulum..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    usermod -aG docker neo
    systemctl enable --now docker
    ok "Docker kuruldu"
else
    warn "Docker zaten kurulu"
fi

# ─── 7. Python 3.11 + pip ───────────────────────
log "7/10 — Python 3.11 kurulum..."
apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3-pip
# pip'i alias olarak ayarla
update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 2>/dev/null || true
ok "Python $(python3.11 --version)"

# ─── 8. PostgreSQL + pgvector (Docker) ──────────
log "8/10 — PostgreSQL 16 + pgvector Docker kurulum..."
mkdir -p /opt/postgres-data /opt/redis-data
cat > /opt/docker-compose.yml << 'EOF'
version: '3.8'
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: fermat_postgres
    restart: unless-stopped
    ports:
      - "127.0.0.1:5432:5432"   # SADECE LOCALHOST'TAN ERİŞ
    environment:
      POSTGRES_DB: fermatai
      POSTGRES_USER: fermat
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
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
      - "127.0.0.1:6379:6379"   # SADECE LOCALHOST'TAN ERİŞ
    volumes:
      - /opt/redis-data:/data
    command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
EOF

# Postgres şifresi oluştur (güvenli)
if [ ! -f /opt/.postgres_password ]; then
    PG_PASS=$(openssl rand -base64 24)
    echo "POSTGRES_PASSWORD=$PG_PASS" > /opt/.postgres_password
    chmod 600 /opt/.postgres_password
    ok "PostgreSQL şifresi oluşturuldu: /opt/.postgres_password"
fi
source /opt/.postgres_password
export POSTGRES_PASSWORD

cd /opt && docker compose up -d
sleep 8
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS vector;" || true
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS unaccent;" || true
ok "PostgreSQL + Redis ayakta"

# ─── 9. nginx + certbot ─────────────────────────
log "9/10 — nginx + certbot (SSL)..."
apt-get install -y -qq nginx certbot python3-certbot-nginx
systemctl enable --now nginx
ok "nginx kurulu ($(nginx -v 2>&1))"

# ─── 10. Playwright + Chromium ──────────────────
log "10/10 — Playwright/Chromium kurulum (Eyotek için)..."
apt-get install -y -qq \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2t64 libdrm2 libxss1 libxtst6 \
    fonts-liberation xvfb
ok "Playwright bağımlılıkları kuruldu"

# ─── FermatAI klasörü ──────────────────────────
log "FermatAI klasörü hazırlanıyor..."
mkdir -p /opt/fermatai /opt/backups/fermatai /var/log/fermatai
chown -R neo:neo /opt/fermatai /opt/backups /var/log/fermatai
ok "Dizinler hazır"

# ─── unattended-upgrades ──────────────────────
log "Otomatik güvenlik güncellemeleri aktif ediliyor..."
dpkg-reconfigure --priority=low unattended-upgrades -fnoninteractive 2>/dev/null || true
ok "Otomatik security patch aktif"

echo ""
echo "============================================"
echo -e "${G}🎉 VPS kurulumu TAMAMLANDI${N}"
echo "============================================"
echo ""
echo "Sonraki adımlar:"
echo "  1. Git repo clone (neo kullanıcısı olarak):"
echo "     sudo -u neo git clone git@github.com:NEO/fermatai.git /opt/fermatai"
echo ""
echo "  2. Python venv + dependencies:"
echo "     cd /opt/fermatai && sudo -u neo python3.11 -m venv .venv"
echo "     sudo -u neo /opt/fermatai/.venv/bin/pip install -r eyotek_agent/requirements.txt"
echo ""
echo "  3. .env dosyasını oluştur ve doldur:"
echo "     sudo -u neo cp /opt/fermatai/vps_setup/.env.production.template /opt/fermatai/.env"
echo "     sudo chmod 600 /opt/fermatai/.env"
echo ""
echo "  4. PostgreSQL şifresi: cat /opt/.postgres_password"
echo "     DATABASE_URL .env'de güncellenmeli"
echo ""
echo "  5. Data migration (laptop'tan):"
echo "     (laptop'ta) pg_dump | gzip > /tmp/fermatai.sql.gz"
echo "     scp /tmp/fermatai.sql.gz neo@VPS:/tmp/"
echo "     (VPS'te) gunzip < /tmp/fermatai.sql.gz | docker exec -i fermat_postgres psql -U fermat -d fermatai"
echo ""
echo "  6. systemd service yerleştir:"
echo "     sudo cp /opt/fermatai/vps_setup/systemd/fermatai-bridge.service /etc/systemd/system/"
echo "     sudo systemctl daemon-reload"
echo "     sudo systemctl enable --now fermatai-bridge"
echo ""
echo "  7. nginx + SSL:"
echo "     sudo cp /opt/fermatai/vps_setup/nginx/fermatai.conf /etc/nginx/sites-available/"
echo "     sudo ln -s /etc/nginx/sites-available/fermatai /etc/nginx/sites-enabled/"
echo "     sudo certbot --nginx -d api.fermategitimkurumlari.com"
echo ""
echo "  8. Meta webhook URL değiştir:"
echo "     https://api.fermategitimkurumlari.com/webhook"
echo ""
echo "============================================"
echo "IP: $(curl -s ifconfig.me || echo 'localhost')"
echo "============================================"
