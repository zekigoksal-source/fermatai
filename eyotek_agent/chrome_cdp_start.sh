#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fermat-chrome-cdp launcher — Playwright Chromium'u VERSIYON-BAGIMSIZ baslatir.
#
# NEDEN: systemd unit'inde chromium binary yolu "chromium-NNNN" diye HARDCODE'luydu.
# Playwright her guncellendiginde (orn 1208 -> 1217) bu klasor degisip yol kiriliyor,
# servis 203/EXEC ile flapping yapiyordu (26 May'da 187006 restart tespit edildi).
# Bu script en guncel "chromium-*" build'ini otomatik bulur => bir daha kirilmaz.
#
# Eyotek 7/24 CDP (port 9333) baglantisinin kaynagi. session_keeper + write_etut bunu kullanir.
# Olusturuldu: 26 May 2026 (teknik borc kapatma — Neo direktif).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HOME_DIR="${HOME:-/home/neo}"
CACHE="${PLAYWRIGHT_BROWSERS_PATH:-$HOME_DIR/.cache/ms-playwright}"
CDP_PORT="${FERMAT_CDP_PORT:-9333}"

# En guncel chromium build'i sec. 'chromium-*' globu, tire yuzunden
# 'chromium_headless_shell-*' (alt-cizgi) build'ini ALMAZ — sadece tam tarayicilar.
# sort -V => versiyona gore artan sirala => tail -1 => en yeni.
CHROME="$(ls -d "$CACHE"/chromium-*/chrome-linux64/chrome 2>/dev/null | sort -V | tail -1 || true)"

if [ -z "${CHROME}" ] || [ ! -x "${CHROME}" ]; then
  echo "[chrome-cdp] FATAL: Playwright chromium binary bulunamadi." >&2
  echo "[chrome-cdp]   arandi: ${CACHE}/chromium-*/chrome-linux64/chrome" >&2
  echo "[chrome-cdp]   cozum:  cd /opt/fermatai && .venv/bin/python -m playwright install chromium" >&2
  exit 1
fi

echo "[chrome-cdp] secilen binary: ${CHROME}"
echo "[chrome-cdp] CDP port: ${CDP_PORT}"

exec "${CHROME}" \
  --headless=new \
  --remote-debugging-port="${CDP_PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${HOME_DIR}/.fermat-chrome" \
  --disable-gpu \
  --no-sandbox \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --disable-extensions \
  --disable-background-networking \
  --disable-default-apps \
  --disable-sync \
  --disable-translate \
  --metrics-recording-only \
  --safebrowsing-disable-auto-update \
  --disable-component-update \
  --window-size=1366,768 \
  --user-agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36" \
  about:blank
