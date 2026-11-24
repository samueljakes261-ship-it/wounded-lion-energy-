#!/usr/bin/env bash
# Start, stop, or inspect the dedicated Onwin Chrome on the VPS.
# This does not start a desktop and does not touch the Kolay90 Chrome.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ACTION="${1:-start}"
if [ -f "$ROOT/experiments/onwin_vps/config.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/experiments/onwin_vps/config.env"
  set +a
fi
PORT="${ONWIN_VPS_CDP_PORT:-9223}"
PROFILE="${ONWIN_VPS_CHROME_PROFILE:-$ROOT/experiments/onwin_vps/chrome_profile}"
DISPLAY_VALUE="${ONWIN_VPS_DISPLAY:-${DISPLAY:-:1}}"
LIVE_PAGE="${ONWIN_VPS_LIVE_PAGE:-https://onwin4505.com/sportsbook/live/main-line/soccer}"
PREMATCH_PAGE="${ONWIN_VPS_PREMATCH_PAGE:-https://onwin4505.com/sportsbook/prelive/main-line/soccer}"
OUTPUT="$ROOT/experiments/onwin_vps/output"
PID_FILE="$OUTPUT/chrome.pid"
LOG_FILE="$OUTPUT/chrome.log"
DISPLAY_NUMBER="${DISPLAY_VALUE#:}"

mkdir -p "$OUTPUT"
chmod 700 "$PROFILE" 2>/dev/null || mkdir -p "$PROFILE"
chmod 700 "$PROFILE" 2>/dev/null || true

python3 -m experiments.onwin_vps.safety --port "$PORT" --profile "$PROFILE"

listening() {
  curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1
}

cmdline_is_ours() {
  local pid="$1"
  local cmd
  cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
  case "$cmd" in
    *"--user-data-dir=${PROFILE}"*) return 0 ;;
    *) return 1 ;;
  esac
}

stop_chrome() {
  if [ ! -f "$PID_FILE" ]; then
    echo "[onwin-vps-chrome] no pid file"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${pid}" ] && cmdline_is_ours "$pid"; then
    kill "$pid" 2>/dev/null || true
    echo "[onwin-vps-chrome] stopped pid ${pid}"
  else
    echo "[onwin-vps-chrome] pid ${pid:-missing} is not the Onwin Chrome; left it alone"
  fi
  rm -f "$PID_FILE"
}

case "$ACTION" in
  stop)
    stop_chrome
    ;;
  restart)
    stop_chrome
    exec "$0" start
    ;;
  status)
    echo "[onwin-vps-chrome] display=${DISPLAY_VALUE} port=${PORT}"
    echo "[onwin-vps-chrome] profile=${PROFILE}"
    if [ -S "/tmp/.X11-unix/X${DISPLAY_NUMBER}" ]; then
      echo "[onwin-vps-chrome] display_socket=yes"
    else
      echo "[onwin-vps-chrome] display_socket=no"
    fi
    if listening; then
      echo "[onwin-vps-chrome] cdp=listening"
      curl -s "http://127.0.0.1:${PORT}/json/version" || true
      echo
    else
      echo "[onwin-vps-chrome] cdp=down"
    fi
    ;;
  start|foreground)
    if [ ! -S "/tmp/.X11-unix/X${DISPLAY_NUMBER}" ]; then
      echo "[onwin-vps-chrome] display ${DISPLAY_VALUE} is not running." >&2
      echo "[onwin-vps-chrome] The existing TigerVNC desktop must already be up. This script will not start one." >&2
      exit 3
    fi
    if listening; then
      echo "[onwin-vps-chrome] already listening on 127.0.0.1:${PORT}"
      exit 0
    fi
    CHROME="$(command -v google-chrome-stable || command -v google-chrome || true)"
    if [ -z "$CHROME" ]; then
      echo "[onwin-vps-chrome] google-chrome was not found" >&2
      exit 1
    fi
    mkdir -p "$PROFILE"
    echo "[onwin-vps-chrome] starting ${CHROME} on 127.0.0.1:${PORT}"
    # Same flags as the working Kolay Chrome. Do not add headless mode,
    # a sandbox bypass, or a GPU bypass: those change the Cloudflare fingerprint.
    export DISPLAY="$DISPLAY_VALUE"
    args=(
      "$CHROME"
      "--remote-debugging-port=${PORT}"
      "--remote-debugging-address=127.0.0.1"
      "--user-data-dir=${PROFILE}"
      "--no-first-run"
      "--no-default-browser-check"
      "--disable-dev-shm-usage"
      "--window-size=1280,900"
      "$LIVE_PAGE"
      "$PREMATCH_PAGE"
    )
    if [ "$ACTION" = "foreground" ]; then
      exec "${args[@]}"
    fi
    nohup "${args[@]}" >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if listening; then
        echo "[onwin-vps-chrome] listening on 127.0.0.1:${PORT}"
        exit 0
      fi
      sleep 0.4
    done
    echo "[onwin-vps-chrome] Chrome did not open its debugging port" >&2
    exit 1
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|foreground}" >&2
    exit 2
    ;;
esac
