#!/bin/bash
# Disaster Recovery Drill (Oturum 25.29 — #5)
# ============================================
# Production'i bozmadan restore prosedurunu test eder.
# Aylik manual run, 1 Haziran 2026 oncesi en az 1x test geregi (Neo karari).
#
# Yaptigi:
#  1. En son backup tarball'i kontrol (son 24h)
#  2. Tarball ic tutarlilik (tar -t)
#  3. Geçici test database oluştur (fermatai_dr_test)
#  4. Backup'tan geçici DB'ye restore
#  5. Saglik kontrol: tablo sayisi + critical row counts
#  6. Test DB'yi sil
#  7. Rapor: PASS/FAIL + sure
#
# Production'a hicbir etki YOK.
# Calistirma: sudo bash /opt/fermatai/vps_setup/scripts/dr_drill.sh

set -euo pipefail

BACKUP_ROOT="/opt/fermatai/backups"
LOG="/var/log/fermatai/dr-drill.log"
TEST_DB="fermatai_dr_test"

mkdir -p "$(dirname "$LOG")"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "$LOG"
}

log "═══════════════════════════════════════════════════"
log "DR DRILL START"

# ─── 1. En yeni backup ─────────────────────────────────
LATEST=$(ls -t "${BACKUP_ROOT}"/*.tar.gz 2>/dev/null | head -1 || true)
if [[ -z "${LATEST}" ]]; then
  log "FAIL: Backup dosyasi bulunamadi"
  exit 1
fi

AGE_SEC=$(( $(date +%s) - $(stat -c %Y "${LATEST}") ))
AGE_H=$(( AGE_SEC / 3600 ))
log "Latest backup: ${LATEST} (${AGE_H}h old)"

if (( AGE_H > 30 )); then
  log "WARN: Backup 30 saatten eski — daily timer çalışmıyor olabilir"
fi

# ─── 2. Tarball icerigi ─────────────────────────────────
log "Tarball icerik kontrol..."
if ! tar -tzf "${LATEST}" >/dev/null 2>&1; then
  log "FAIL: Tarball bozuk"
  exit 1
fi

# DB dump dosyasi var mi
SQL_FILE_IN_TAR=$(tar -tzf "${LATEST}" | grep -E '\.sql\.gz$' | head -1)
if [[ -z "${SQL_FILE_IN_TAR}" ]]; then
  log "FAIL: Tarball icinde .sql.gz bulunamadi"
  exit 1
fi
log "  ✓ DB dump: ${SQL_FILE_IN_TAR}"

# ─── 3. Test DB oluştur ─────────────────────────────────
log "Test DB hazırlanıyor: ${TEST_DB}"
docker exec fermat_postgres psql -U fermat -d postgres \
  -c "DROP DATABASE IF EXISTS ${TEST_DB};" >/dev/null 2>&1 || true
docker exec fermat_postgres psql -U fermat -d postgres \
  -c "CREATE DATABASE ${TEST_DB};" >/dev/null

# ─── 4. Tarball'dan SQL extract + restore ──────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Tarball extract ediliyor..."
tar -xzf "${LATEST}" -C "${TMP}"

DUMP_PATH=$(find "${TMP}" -name "*.sql.gz" -type f | head -1)
if [[ -z "${DUMP_PATH}" ]]; then
  log "FAIL: Extract sonrasi dump bulunamadi"
  exit 1
fi

log "Restore başlıyor → ${TEST_DB}"
START_TIME=$(date +%s)
gunzip -c "${DUMP_PATH}" | docker exec -i fermat_postgres \
  psql -U fermat -d "${TEST_DB}" --quiet >/dev/null 2>&1 || {
    log "WARN: Restore'da uyarılar var (extension/role hataları normal — devam)"
}

# Extensions
docker exec fermat_postgres psql -U fermat -d "${TEST_DB}" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null 2>&1 || true
docker exec fermat_postgres psql -U fermat -d "${TEST_DB}" \
  -c "CREATE EXTENSION IF NOT EXISTS unaccent;" >/dev/null 2>&1 || true

ELAPSED=$(( $(date +%s) - START_TIME ))
log "Restore tamamlandi: ${ELAPSED}s"

# ─── 5. Sağlık kontrol ─────────────────────────────────
log "Sağlık kontrol..."

check_count() {
  local table="$1"
  local min="$2"
  local cnt
  cnt=$(docker exec fermat_postgres psql -U fermat -d "${TEST_DB}" -t -A \
    -c "SELECT COUNT(*) FROM fermat.${table};" 2>/dev/null || echo 0)
  if (( cnt >= min )); then
    log "  ✓ ${table}: ${cnt} kayit (min ${min})"
    return 0
  else
    log "  ✗ ${table}: ${cnt} kayit (min ${min} bekleniyor)"
    return 1
  fi
}

FAILED=0
check_count "students" 100 || FAILED=$((FAILED+1))
check_count "staff" 10 || FAILED=$((FAILED+1))
check_count "agent_conversations" 100 || FAILED=$((FAILED+1))
check_count "student_exams" 1000 || FAILED=$((FAILED+1))
check_count "rag_content" 30 || FAILED=$((FAILED+1))

# ─── 6. Cleanup ────────────────────────────────────────
log "Test DB siliniyor..."
docker exec fermat_postgres psql -U fermat -d postgres \
  -c "DROP DATABASE IF EXISTS ${TEST_DB};" >/dev/null

# ─── 7. Sonuc ──────────────────────────────────────────
if (( FAILED == 0 )); then
  log "═══════════════════════════════════════════════════"
  log "DR DRILL: PASS ✓"
  log "  Backup yaşı: ${AGE_H}h"
  log "  Restore süresi: ${ELAPSED}s"
  log "  Tüm sağlık kontrolleri geçti"
  log "═══════════════════════════════════════════════════"
  exit 0
else
  log "═══════════════════════════════════════════════════"
  log "DR DRILL: FAIL ✗"
  log "  ${FAILED} sağlık kontrolü başarısız"
  log "═══════════════════════════════════════════════════"
  exit 1
fi
