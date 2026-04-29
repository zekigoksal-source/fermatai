#!/bin/bash
# Atlas Nightly Auto-Scan (Oturum 25.29 — #4)
# ==============================================
# Her gece 02:30 UTC çalışır:
#   1. observer → atlas_observations (anomali tespit)
#   2. advisor  → atlas_suggestions (gözlemden öneri)
#   3. JSON özet + admin'e WP bildirim (kritik varsa)
#
# Çıkış: /var/log/fermatai/atlas-nightly.log

set -euo pipefail

cd /opt/fermatai/eyotek_agent

LOG_DIR="/var/log/fermatai"
LOG_FILE="${LOG_DIR}/atlas-nightly.log"
SUMMARY_FILE="/tmp/atlas-summary-$(date +%Y%m%d).json"

mkdir -p "${LOG_DIR}"

echo "═══════════════════════════════════════════════════" >> "${LOG_FILE}"
echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Atlas nightly start" >> "${LOG_FILE}"

# 1. Observer — son 24h tara
echo "[$(date -u '+%H:%M:%S')] OBSERVE start" >> "${LOG_FILE}"
/opt/fermatai/.venv/bin/python -m atlas observe --hours 24 >> "${LOG_FILE}" 2>&1 \
  || echo "[$(date -u '+%H:%M:%S')] OBSERVE failed (continuing)" >> "${LOG_FILE}"

# 2. Advisor — gözlemden öneri üret
echo "[$(date -u '+%H:%M:%S')] ADVISE start" >> "${LOG_FILE}"
/opt/fermatai/.venv/bin/python -m atlas advise >> "${LOG_FILE}" 2>&1 \
  || echo "[$(date -u '+%H:%M:%S')] ADVISE failed (continuing)" >> "${LOG_FILE}"

# 3. Özet — kritik bulgular
/opt/fermatai/.venv/bin/python /opt/fermatai/eyotek_agent/atlas_nightly_summary.py \
  > "${SUMMARY_FILE}" 2>> "${LOG_FILE}" || true

if [[ -s "${SUMMARY_FILE}" ]]; then
  cat "${SUMMARY_FILE}" >> "${LOG_FILE}"
fi

echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Atlas nightly done" >> "${LOG_FILE}"
echo "" >> "${LOG_FILE}"
