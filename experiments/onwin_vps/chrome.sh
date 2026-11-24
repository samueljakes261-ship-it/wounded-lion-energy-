#!/usr/bin/env bash
# Start, stop, or inspect the dedicated Onwin Chrome on the VPS.
# Normal Google Chrome on a private Xvfb screen. Not VNC, not display :1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ACTION="${1:-start}"
echo "[onwin-vps-chrome] ${ACTION} beginning" >&2
if [ -f "$ROOT/experiments/onwin_vps/config.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/experiments/onwin_vps/config.env"
  set +a
fi
PORT="${ONWIN_VPS_CDP_PORT:-9223}"
PROFILE="${ONWIN_VPS_CHROME_PROFILE:-$ROOT/experiments/onwin_vps/chrome_profile}"
DISPLAY_VALUE="${ONWIN_VPS_DISPLAY:-:98}"
if [ "$DISPLAY_VALUE" = ":1" ]; then
  echo "[onwin-vps-chrome] display :1 belongs to Kolay90; using :98"
  DISPLAY_VALUE=":98"
fi
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
  curl -sf --connect-timeout 2 --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1
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

ensure_display() {
  local number="${DISPLAY_VALUE#:}"
  if [ -S "/tmp/.X11-unix/X${number}" ]; then
    return 0
  fi
  local xvfb
  xvfb="$(command -v Xvfb || true)"
  if [ -z "$xvfb" ]; then
    echo "[onwin-vps-chrome] Xvfb is not installed." >&2
    echo "[onwin-vps-chrome] Onwin Chrome needs its own screen. This does not use VNC." >&2
    echo "[onwin-vps-chrome] Install it with: sudo apt-get install -y xvfb" >&2
    exit 1
  fi
  echo "[onwin-vps-chrome] starting Xvfb on ${DISPLAY_VALUE}"
  nohup "$xvfb" "$DISPLAY_VALUE" -screen 0 1280x900x24 -ac +extension GLX +render -noreset >>"$OUTPUT/xvfb.log" 2>&1 &
  echo $! >"$OUTPUT/xvfb.pid"
  local _i
  for _i in $(seq 1 25); do
    if [ -S "/tmp/.X11-unix/X${number}" ]; then
      return 0
    fi
    sleep 0.2
  done
  echo "[onwin-vps-chrome] Xvfb did not create ${DISPLAY_VALUE}" >&2
  exit 1
}

stop_xvfb() {
  local pid cmd
  pid="$(cat "$OUTPUT/xvfb.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && [ -r "/proc/${pid}/cmdline" ]; then
    cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)" 2>/dev/null || true
    case "$cmd" in
      *Xvfb*"${DISPLAY_VALUE}"*)
        kill "$pid" 2>/dev/null || true
        echo "[onwin-vps-chrome] stopped Xvfb on ${DISPLAY_VALUE}"
        ;;
    esac
  fi
  rm -f "$OUTPUT/xvfb.pid"
}

ensure_memory() {
  local avail
  avail="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || true)"
  if [ -n "$avail" ] && [ "$avail" -lt 400000 ]; then
    echo "[onwin-vps-chrome] only ${avail} kB memory available. Not starting Chrome, so the VPS stays reachable." >&2
    exit 1
  fi
}

launch_chrome() {
  mkdir -p "$PROFILE"
  export DISPLAY="$DISPLAY_VALUE"
  args=(
    "$CHROME"
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
  args+=("$LIVE_PAGE" "$PREMATCH_PAGE")
  if [ "$ACTION" = "foreground" ]; then
    exec "${args[@]}"
  fi
  echo "---- $(date -Is) display=${DISPLAY_VALUE} $* ----" >>"$LOG_FILE"
  nohup "${args[@]}" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
}

stop_other_starters() {
  local pid args
  while read -r pid args; do
    [ -n "${pid}" ] || continue
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "$PPID" ] && continue
    case "$args" in
      *experiments/onwin_vps/chrome.sh*)
        echo "[onwin-vps-chrome] stopping stuck chrome.sh pid ${pid}" >&2
        kill "$pid" 2>/dev/null || true
        ;;
    esac
  done < <(ps -eo pid=,args=)
}

case "$ACTION" in
  stop)
    stop_chrome
    stop_xvfb
    ;;
  restart)
    stop_chrome
    echo "[onwin-vps-chrome] starting a new Onwin Chrome"
    exec "$0" start
    ;;
  install)
    install_chrome
    echo "[onwin-vps-chrome] installed $(find_chrome)"
    ;;
  status)
    echo "[onwin-vps-chrome] display=${DISPLAY_VALUE} port=${PORT}"
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
    echo "[onwin-vps-chrome] launch requested on port ${PORT}" >&2
    exec 9>"$OUTPUT/chrome.start.lock"
    if ! flock -n 9; then
      echo "[onwin-vps-chrome] another chrome.sh holds the launch lock" >&2
      stop_other_starters
      sleep 1
      if ! flock -w 10 9; then
        echo "[onwin-vps-chrome] the other start did not finish" >&2
        exit 1
      fi
    fi
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
    ensure_display
    ensure_memory
    release_our_chrome
    : >"$LOG_FILE"
    echo "[onwin-vps-chrome] starting ${CHROME} on ${DISPLAY_VALUE} port 127.0.0.1:${PORT}"
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
