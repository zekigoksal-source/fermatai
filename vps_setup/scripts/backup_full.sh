#!/bin/bash
# FermatAI Backup Automation (Oturum 25.9 - T5)
# 3 katmanli yedek: PG dump + .env/cookie + Atlas-2 snapshot
# Lokasyon: /opt/fermatai/backups/{YYYY-MM-DD}.tar.gz
# Retention: 14 gun
# Run: cron (her gece 03:00 fermatai-backup.timer)

set -e
BACKUP_ROOT="/opt/fermatai/backups"
TODAY=$(date +%Y-%m-%d)
BACKUP_DIR="$BACKUP_ROOT/$TODAY"
mkdir -p "$BACKUP_DIR"
echo "[backup] Starting full backup -> $BACKUP_DIR"

# 1. Postgres dump
echo "[backup] PostgreSQL dump..."
docker exec fermat_postgres pg_dump -U fermat -d fermatai --clean --if-exists \
  | gzip > "$BACKUP_DIR/fermatai_db_${TODAY}.sql.gz"
DB_SIZE=$(du -h "$BACKUP_DIR/fermatai_db_${TODAY}.sql.gz" | cut -f1)
echo "[backup] DB done ($DB_SIZE)"

# 2. Critical files
mkdir -p "$BACKUP_DIR/files"
[ -f /opt/fermatai/.env ] && cp /opt/fermatai/.env "$BACKUP_DIR/files/.env" && chmod 600 "$BACKUP_DIR/files/.env"
[ -f /opt/fermatai/eyotek_agent/.eyotek_status.json ] && cp /opt/fermatai/eyotek_agent/.eyotek_status.json "$BACKUP_DIR/files/"
[ -f /opt/fermatai/eyotek_agent/.eyotek_cookies.json ] && cp /opt/fermatai/eyotek_agent/.eyotek_cookies.json "$BACKUP_DIR/files/"
[ -f /opt/fermatai/eyotek_agent/.analytics_cache.json ] && cp /opt/fermatai/eyotek_agent/.analytics_cache.json "$BACKUP_DIR/files/"

# 3. Atlas-2 snapshot
docker exec fermat_postgres psql -U fermat -d fermatai -t -A -c \
  "SELECT row_to_json(t) FROM (SELECT * FROM prompt_suggestions ORDER BY created_at DESC LIMIT 100) t" \
  > "$BACKUP_DIR/atlas2_suggestions_${TODAY}.jsonl" 2>/dev/null || echo "[backup] atlas2 snapshot skipped"

# 4. Tarball
cd "$BACKUP_ROOT"
tar -czf "${TODAY}.tar.gz" "$TODAY/"
TAR_SIZE=$(du -h "${TODAY}.tar.gz" | cut -f1)
rm -rf "$BACKUP_DIR"
echo "[backup] Tarball: ${TODAY}.tar.gz ($TAR_SIZE)"

# 5. Retention 14 gun
find "$BACKUP_ROOT" -name "*.tar.gz" -type f -mtime +14 -delete
REMAINING=$(ls "$BACKUP_ROOT"/*.tar.gz 2>/dev/null | wc -l)
echo "[backup] $REMAINING backup retained"

# 6. Health log
echo "[backup] $(date '+%Y-%m-%d %H:%M:%S') OK ($TAR_SIZE)" >> "$BACKUP_ROOT/backup.log"
