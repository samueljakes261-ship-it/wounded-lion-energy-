#!/usr/bin/env bash
# Launch the operator Chrome used by Kolay90 and BetKanyon prematch.
# Cloudflare / terms / login stay in this window. Do not close it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${KOLAY90_CHROME_PROFILE:-$ROOT/experiments/kolay90_direct/chrome_profile}"
PORT="${KOLAY90_CDP_PORT:-9222}"
SPORT_PAGE="${BETKANYON_SPORT_PAGE:-https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad/Tools/RequestHelper}"

mkdir -p "$PROFILE"

if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "[prematch-chrome] already listening on 127.0.0.1:${PORT}"
  curl -s "http://127.0.0.1:${PORT}/json/list" || true
  exit 0
fi

CHROME="$(command -v google-chrome-stable || command -v google-chrome || true)"
if [ -z "$CHROME" ]; then
  echo "[prematch-chrome] google-chrome not found" >&2
  exit 1
fi

echo "[prematch-chrome] starting $CHROME on port ${PORT}"
echo "[prematch-chrome] tabs: https://kolay90.com/  $SPORT_PAGE"
exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --no-sandbox \
  --disable-gpu \
  --window-size=1280,900 \
  "https://kolay90.com/" \
  "$SPORT_PAGE"
