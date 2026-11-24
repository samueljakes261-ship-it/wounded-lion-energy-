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
  local cmd=""
  local proc="/proc/${pid}/cmdline"
  if [ -r "$proc" ]; then
    cmd="$(tr '\0' ' ' < "$proc" 2>/dev/null || true)" 2>/dev/null || true
  fi
  case "$cmd" in
    *"--user-data-dir=${PROFILE}"*) return 0 ;;
    *) return 1 ;;
  esac
}

our_pids() {
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && cmdline_is_ours "$pid"; then
    printf '%s\n' "$pid"
  fi
  local found
  while read -r found; do
    [ -n "$found" ] || continue
    if cmdline_is_ours "$found"; then
      printf '%s\n' "$found"
    fi
  done < <(pgrep -f -- "--user-data-dir=${PROFILE}" || true)
}

release_our_chrome() {
  local pid
  while read -r pid; do
    [ -n "$pid" ] || continue
    kill "$pid" 2>/dev/null || true
  done < <(our_pids | sort -u)
  sleep 0.4
  while read -r pid; do
    [ -n "$pid" ] || continue
    kill -9 "$pid" 2>/dev/null || true
  done < <(our_pids | sort -u)
  rm -f "$PID_FILE"
  rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonCookie" "$PROFILE/SingletonSocket"
}

stop_chrome() {
  local before
  before="$(our_pids | sort -u || true)"
  if [ -z "$before" ]; then
    echo "[onwin-vps-chrome] Onwin Chrome was not running"
    rm -f "$PID_FILE"
    return 0
  fi
  release_our_chrome
  echo "[onwin-vps-chrome] stopped the Onwin Chrome"
}

show_log() {
  echo "[onwin-vps-chrome] last log lines:" >&2
  if [ -f "$LOG_FILE" ]; then
    tail -n 40 "$LOG_FILE" >&2 || true
  else
    echo "[onwin-vps-chrome] no log file" >&2
  fi
  if grep -qi 'shared librar' "$LOG_FILE" 2>/dev/null; then
    echo "[onwin-vps-chrome] Chrome is missing a library. After apt finishes, run: sudo apt-get install -f -y" >&2
  fi
}

wait_for_cdp() {
  local _i
  for _i in $(seq 1 30); do
    if listening; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

launch_chrome() {
  mkdir -p "$PROFILE"
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
  )
  if [ "$#" -gt 0 ]; then
    args+=("$@")
  fi
  # Headless Chrome rejects more than one startup address. The collector
  # opens the prematch tab after it attaches.
  args+=("$LIVE_PAGE")
  if [ "$ACTION" = "foreground" ]; then
    exec "${args[@]}"
  fi
  echo "---- $(date -Is) $* ----" >>"$LOG_FILE"
  nohup "${args[@]}" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
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
    exec 9>"$OUTPUT/chrome.start.lock"
    flock -w 45 9
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
    release_our_chrome
    : >"$LOG_FILE"
    echo "[onwin-vps-chrome] starting headless ${CHROME} on 127.0.0.1:${PORT}"
    launch_chrome
    if wait_for_cdp; then
      echo "[onwin-vps-chrome] listening on 127.0.0.1:${PORT}"
      exit 0
    fi
    echo "[onwin-vps-chrome] Chrome did not open its debugging port" >&2
    show_log
    echo "[onwin-vps-chrome] retrying without the Chrome sandbox" >&2
    release_our_chrome
    launch_chrome --no-sandbox
    if wait_for_cdp; then
      echo "[onwin-vps-chrome] listening on 127.0.0.1:${PORT}"
      exit 0
    fi
    echo "[onwin-vps-chrome] Chrome did not open its debugging port" >&2
    show_log
    exit 1
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|install|foreground}" >&2
    exit 2
    ;;
esac
