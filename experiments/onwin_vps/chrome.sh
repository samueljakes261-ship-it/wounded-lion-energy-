#!/usr/bin/env bash
# Start, stop, or inspect the dedicated Onwin Chrome on the VPS.
# Headless Google Chrome. No VNC desktop and no Kolay90 profile.
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
LIVE_PAGE="${ONWIN_VPS_LIVE_PAGE:-https://onwin4505.com/sportsbook/live/main-line/soccer}"
PREMATCH_PAGE="${ONWIN_VPS_PREMATCH_PAGE:-https://onwin4505.com/sportsbook/prelive/main-line/soccer}"
OUTPUT="$ROOT/experiments/onwin_vps/output"
PID_FILE="$OUTPUT/chrome.pid"
LOG_FILE="$OUTPUT/chrome.log"

mkdir -p "$OUTPUT"
chmod 700 "$PROFILE" 2>/dev/null || mkdir -p "$PROFILE"
chmod 700 "$PROFILE" 2>/dev/null || true

python3 -m experiments.onwin_vps.safety --port "$PORT" --profile "$PROFILE"

listening() {
  curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1
}

find_chrome() {
  if [ -n "${ONWIN_VPS_CHROME_BIN:-}" ] && [ -x "${ONWIN_VPS_CHROME_BIN}" ]; then
    printf '%s\n' "$ONWIN_VPS_CHROME_BIN"
    return 0
  fi
  local path name old_path
  old_path="$PATH"
  PATH="${PATH}:/usr/local/bin:/snap/bin"
  for name in google-chrome-stable google-chrome chromium chromium-browser; do
    path="$(command -v "$name" 2>/dev/null || true)"
    if [ -n "$path" ]; then
      PATH="$old_path"
      printf '%s\n' "$path"
      return 0
    fi
  done
  PATH="$old_path"
  for path in \
    /usr/bin/google-chrome-stable \
    /usr/bin/google-chrome \
    /usr/bin/chromium \
    /usr/bin/chromium-browser \
    /snap/bin/chromium \
    /opt/google/chrome/google-chrome \
    /opt/google/chrome/chrome
  do
    if [ -x "$path" ]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

install_chrome() {
  local arch deb
  arch="$(uname -m)"
  if [ "$arch" != "x86_64" ]; then
    echo "[onwin-vps-chrome] Google Chrome packages are built for x86_64, this host is ${arch}" >&2
    exit 1
  fi
  deb="$(mktemp --suffix=.deb)"
  echo "[onwin-vps-chrome] downloading Google Chrome"
  curl -fsSL -o "$deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y "$deb"
  rm -f "$deb"
  find_chrome >/dev/null
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
  install)
    install_chrome
    echo "[onwin-vps-chrome] installed $(find_chrome)"
    ;;
  status)
    echo "[onwin-vps-chrome] headless port=${PORT}"
    echo "[onwin-vps-chrome] profile=${PROFILE}"
    if chrome_bin="$(find_chrome)"; then
      echo "[onwin-vps-chrome] chrome_bin=${chrome_bin}"
    else
      echo "[onwin-vps-chrome] chrome_bin=missing"
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
    if listening; then
      echo "[onwin-vps-chrome] already listening on 127.0.0.1:${PORT}"
      exit 0
    fi
    CHROME="$(find_chrome || true)"
    if [ -z "$CHROME" ]; then
      echo "[onwin-vps-chrome] Google Chrome was not found." >&2
      echo "[onwin-vps-chrome] Install it with: experiments/onwin_vps/chrome.sh install" >&2
      exit 1
    fi
    mkdir -p "$PROFILE"
    echo "[onwin-vps-chrome] starting headless ${CHROME} on 127.0.0.1:${PORT}"
    args=(
      "$CHROME"
      "--headless=new"
      "--remote-debugging-port=${PORT}"
      "--remote-debugging-address=127.0.0.1"
      "--remote-allow-origins=*"
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
    echo "usage: $0 {start|stop|restart|status|install|foreground}" >&2
    exit 2
    ;;
esac
