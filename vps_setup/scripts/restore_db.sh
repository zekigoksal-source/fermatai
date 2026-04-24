#!/bin/bash
# ===================================================
# FermatAI — Kriz Anında Database Restore
# ===================================================
# Kullanım:
#   bash restore_db.sh /opt/backups/fermatai/fermatai_20260424_030000.sql.gz
# ===================================================

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Kullanım: $0 <backup_file.sql.gz>"
    echo ""
    echo "Mevcut yedekler:"
    ls -lh /opt/backups/fermatai/*.sql.gz 2>/dev/null | tail -10
    exit 1
fi

BACKUP="$1"

if [ ! -f "$BACKUP" ]; then
    echo "❌ Yedek bulunamadı: $BACKUP"
    exit 1
fi

log() { echo "[$(date +'%F %T')] $*"; }

log "⚠️  DIKKAT: Bu mevcut DB'yi TAMAMEN SILIP yedekten geri yükleyecek!"
read -p "Devam etmek için 'EVET' yaz: " CONFIRM
if [ "$CONFIRM" != "EVET" ]; then
    log "İptal edildi"
    exit 0
fi

# ─── 1. Bridge'i durdur ─────────────────────────
log "🛑 Bridge durduruluyor..."
sudo systemctl stop fermatai-bridge

# ─── 2. Mevcut DB'yi yedekle (güvenlik) ────────
SAFETY_BACKUP="/tmp/fermat_before_restore_$(date +%s).sql.gz"
log "💾 Mevcut DB güvenlik yedeği: $SAFETY_BACKUP"
docker exec fermat_postgres pg_dump -U fermat -d fermatai | gzip > "$SAFETY_BACKUP"

# ─── 3. DB'yi sıfırla ──────────────────────────
log "🗑  DB sıfırlanıyor..."
docker exec fermat_postgres psql -U fermat -d postgres -c "DROP DATABASE IF EXISTS fermatai;"
docker exec fermat_postgres psql -U fermat -d postgres -c "CREATE DATABASE fermatai;"

# ─── 4. Restore ────────────────────────────────
log "📥 Restore başlıyor: $BACKUP"
gunzip < "$BACKUP" | docker exec -i fermat_postgres psql -U fermat -d fermatai

# ─── 5. Extensions tekrar kur ──────────────────
log "🔌 pgvector + unaccent extension..."
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec fermat_postgres psql -U fermat -d fermatai -c "CREATE EXTENSION IF NOT EXISTS unaccent;"

# ─── 6. Sağlık kontrol ────────────────────────
ROW_COUNT=$(docker exec fermat_postgres psql -U fermat -d fermatai -t -c "SELECT count(*) FROM students;")
log "✅ students tablosu: $ROW_COUNT kayıt"

# ─── 7. Bridge başlat ─────────────────────────
log "🚀 Bridge başlatılıyor..."
sudo systemctl start fermatai-bridge
sleep 3
if systemctl is-active --quiet fermatai-bridge; then
    log "✅ Bridge çalışıyor"
else
    log "❌ Bridge başlatılamadı! Log:"
    journalctl -u fermatai-bridge -n 30 --no-pager
fi

log "🎉 Restore tamamlandı"
log "ℹ️  Güvenlik yedeği: $SAFETY_BACKUP (24 saat içinde silmeyi unutma)"
