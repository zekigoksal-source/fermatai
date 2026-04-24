#!/bin/bash
# ===================================================
# FermatAI Deploy Script
# Her git push sonrası laptop'tan veya VPS'te çalışır
# ===================================================
# Kullanım (laptop'tan):
#   ssh neo@fermatai-prod "cd /opt/fermatai && bash vps_setup/scripts/deploy.sh"
#
# Veya VPS'te direkt:
#   bash /opt/fermatai/vps_setup/scripts/deploy.sh
# ===================================================

set -euo pipefail
trap 'echo "[ERROR] Deploy başarısız: satır $LINENO" >&2' ERR

FERMAT_DIR="/opt/fermatai"
SERVICE="fermatai-bridge"
VENV="$FERMAT_DIR/.venv"

log() { echo "[$(date +'%H:%M:%S')] $*"; }

cd "$FERMAT_DIR"

# ─── 1. Git pull ────────────────────────────────
log "📥 Git pull..."
BEFORE=$(git rev-parse HEAD)
git pull --rebase origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" == "$AFTER" ]; then
    log "⏭  Değişiklik yok, restart'a gerek YOK"
    exit 0
fi

log "📦 Yeni commitler:"
git log --oneline "$BEFORE..$AFTER" | head -10

# ─── 2. requirements güncelleme kontrol ─────────
if git diff "$BEFORE..$AFTER" --name-only | grep -q "requirements.txt"; then
    log "📦 requirements.txt değişmiş, pip install..."
    "$VENV/bin/pip" install -q -r "$FERMAT_DIR/eyotek_agent/requirements.txt"
fi

# ─── 3. DB migration gerekiyor mu? ──────────────
if git diff "$BEFORE..$AFTER" --name-only | grep -qE "db_schema.sql|acl_schema.sql"; then
    log "⚠️  DB schema değişmiş! Manuel migration gerekli olabilir."
    log "   SQL dosyalarını incele + psql ile uygula."
fi

# ─── 4. Service restart ─────────────────────────
log "🔄 $SERVICE restart..."
sudo systemctl restart "$SERVICE"

sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    log "✅ $SERVICE çalışıyor"
else
    log "❌ $SERVICE başlatılamadı! Log:"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
fi

# ─── 5. Smoke test ──────────────────────────────
sleep 2
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/chat)
if [ "$HTTP_CODE" == "200" ]; then
    log "✅ Smoke test geçti (/chat → HTTP 200)"
else
    log "⚠️  Smoke test başarısız: HTTP $HTTP_CODE"
fi

log "🎉 Deploy tamamlandı"
