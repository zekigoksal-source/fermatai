#!/bin/bash
# ===================================================
# FermatAI — PostgreSQL Günlük Yedek
# ===================================================
# Crontab: 0 3 * * * /opt/fermatai/vps_setup/scripts/backup_db.sh
# ===================================================

set -euo pipefail

BACKUP_DIR="/opt/backups/fermatai"
RETENTION_DAYS=14
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/fermatai_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

log() { echo "[$(date +'%F %T')] $*"; }

log "📦 PostgreSQL yedek alınıyor..."

# Docker içinden pg_dump
docker exec fermat_postgres pg_dump -U fermat -d fermatai --no-owner --no-privileges \
    | gzip -9 > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "✅ Yedek tamam: $BACKUP_FILE ($SIZE)"

# ─── Eski yedekleri temizle ─────────────────────
log "🧹 $RETENTION_DAYS günden eski yedekler siliniyor..."
find "$BACKUP_DIR" -name "fermatai_*.sql.gz" -mtime +$RETENTION_DAYS -delete
REMAINING=$(find "$BACKUP_DIR" -name "fermatai_*.sql.gz" | wc -l)
log "📂 Kalan yedek sayısı: $REMAINING"

# ─── Uzak yedek (opsiyonel — rclone kurulduysa) ─
if command -v rclone &>/dev/null && rclone listremotes 2>/dev/null | grep -q "fermat-backup:"; then
    log "☁️  Uzak buluta yükleniyor..."
    rclone copy "$BACKUP_FILE" "fermat-backup:fermatai-db/" --progress
    log "✅ Uzak yedek tamam"
else
    log "ℹ️  rclone yapılandırılmamış — sadece local yedek"
fi

# ─── Sağlık kontrol ────────────────────────────
if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
    # Gzip bütünlük kontrolü
    if gunzip -t "$BACKUP_FILE" 2>/dev/null; then
        log "✅ Yedek bütünlük OK"
        exit 0
    fi
fi

log "❌ YEDEK HATASI — admin'e bildir"
exit 1
