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

pids_listening_on_port() {
  local hex inode pid fd target
  hex="$(printf '%04X' "$PORT")"
  while read -r inode; do
    [ -n "$inode" ] && [ "$inode" != "0" ] || continue
    for pid in /proc/[0-9]*; do
      pid="${pid#/proc/}"
      for fd in "/proc/${pid}/fd/"*; do
        [ -L "$fd" ] || continue
        target="$(readlink "$fd" 2>/dev/null || true)"
        case "$target" in
          "socket:[${inode}]")
            printf '%s\n' "$pid"
            break
            ;;
        esac
      done
    done
  done < <(awk -v hex="$hex" 'NR > 1 && toupper($4) == "0A" && toupper($2) ~ ":" hex "$" {print $10}' /proc/net/tcp /proc/net/tcp6 2>/dev/null)
}

kill_port_holders() {
  local signal="${1:-TERM}" pid cmd
  while read -r pid; do
    [ -n "$pid" ] || continue
    cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *chrome*|*chromium*|*Chrome*)
        echo "[onwin-vps-chrome] stopping pid ${pid} on port ${PORT}" >&2
        kill -s "$signal" "$pid" 2>/dev/null || true
        ;;
    esac
  done < <(pids_listening_on_port | sort -u)
}

debugger_ready() {
  ONWIN_CDP_PORT="$PORT" python3 -c '
import json, os, socket, urllib.request
port = int(os.environ["ONWIN_CDP_PORT"])
try:
    with urllib.request.urlopen("http://127.0.0.1:%s/json/version" % port, timeout=2) as response:
        info = json.loads(response.read().decode("utf-8", "replace"))
    ws = str(info.get("webSocketDebuggerUrl") or "")
    prefix = "ws://127.0.0.1:%s" % port
    if not ws.startswith(prefix):
        raise SystemExit(1)
    path = ws[len(prefix):] or "/"
    request = (
        "GET %s HTTP/1.1\r\nHost: 127.0.0.1:%s\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ) % (path, port)
    sock = socket.create_connection(("127.0.0.1", port), 3)
    try:
        sock.settimeout(3)
        sock.sendall(request.encode("ascii"))
        data = sock.recv(128)
    finally:
        sock.close()
    ok = b" 101 " in data[:40]
    raise SystemExit(0 if ok else 1)
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
'
}

stop_chrome() {
  release_our_chrome
  kill_port_holders TERM
  sleep 0.4
  kill_port_holders KILL
  rm -f "$PID_FILE"
  rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonCookie" "$PROFILE/SingletonSocket"
  local _i
  for _i in $(seq 1 20); do
    if ! listening; then
      echo "[onwin-vps-chrome] stopped the Onwin Chrome"
      return 0
    fi
    sleep 0.25
  done
  echo "[onwin-vps-chrome] port ${PORT} is still open" >&2
  return 1
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
  # Close the launch-lock fd. A background Xvfb must not keep the lock after this script exits.
  nohup "$xvfb" "$DISPLAY_VALUE" -screen 0 1280x900x24 -ac +extension GLX +render -noreset >>"$OUTPUT/xvfb.log" 2>&1 9>&- &
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
    "--disable-background-timer-throttling"
    "--disable-backgrounding-occluded-windows"
    "--disable-renderer-backgrounding"
    "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling"
    "--window-size=1280,900"
  )
  if [ "$#" -gt 0 ]; then
    args+=("$@")
  fi
  # A profile that already passed Cloudflare must come back as it was.
  # Opening the default host again reloads both sportsbook tabs.
  if [ -d "$PROFILE/Default" ]; then
    args+=("--restore-last-session")
  else
    args+=("$LIVE_PAGE" "$PREMATCH_PAGE")
  fi
  if [ "$ACTION" = "foreground" ]; then
    exec 9>&-
    exec "${args[@]}"
  fi
  echo "---- $(date -Is) display=${DISPLAY_VALUE} $* ----" >>"$LOG_FILE"
  # Close the launch-lock fd. Chrome must not keep the lock after this script exits.
  nohup "${args[@]}" >>"$LOG_FILE" 2>&1 9>&- &
  echo $! >"$PID_FILE"
}

lock_holders() {
  local pid_dir pid fd target lock_path
  lock_path="$(readlink -f "$OUTPUT/chrome.start.lock" 2>/dev/null || printf '%s' "$OUTPUT/chrome.start.lock")"
  for pid_dir in /proc/[0-9]*; do
    pid="${pid_dir#/proc/}"
    [ "$pid" = "$$" ] && continue
    [ "$pid" = "${BASHPID:-}" ] && continue
    [ "$pid" = "$PPID" ] && continue
    for fd in "$pid_dir"/fd/*; do
      [ -L "$fd" ] || continue
      target="$(readlink "$fd" 2>/dev/null || true)"
      case "$target" in
        "$lock_path"|"$lock_path (deleted)")
          printf '%s\n' "$pid"
          break
          ;;
      esac
    done
  done
}

release_lock_holders() {
  local signal="${1:-TERM}" pid cmd
  local -a pids=()
  while read -r pid; do
    [ -n "$pid" ] || continue
    pids+=("$pid")
  done < <(lock_holders 9>&-)
  for pid in "${pids[@]+"${pids[@]}"}"; do
    cmd="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
    echo "[onwin-vps-chrome] releasing launch lock held by pid ${pid} (${signal}): ${cmd}" >&2
    kill -s "$signal" "$pid" 2>/dev/null || true
  done
}

case "$ACTION" in
  stop)
    stop_chrome
    stop_xvfb
    ;;
  restart)
    stop_chrome || true
    if listening; then
      echo "[onwin-vps-chrome] could not free port ${PORT}" >&2
      exit 1
    fi
    # systemd restarts the Chrome service a few seconds after the process dies.
    sleep 6
    if listening && debugger_ready; then
      echo "[onwin-vps-chrome] Chrome came back and the debugger accepts a client"
      exit 0
    fi
    if listening; then
      echo "[onwin-vps-chrome] port ${PORT} is open but the debugger does not accept a client" >&2
      stop_chrome || true
    fi
    echo "[onwin-vps-chrome] starting a new Onwin Chrome"
    exec "$0" start
    ;;
  reclaim-lock)
    release_lock_holders TERM
    sleep 0.4
    release_lock_holders KILL
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
      echo "[onwin-vps-chrome] another start holds the launch lock" >&2
      release_lock_holders TERM
      sleep 0.4
      release_lock_holders KILL
      sleep 0.2
      if ! flock -w 5 9; then
        echo "[onwin-vps-chrome] the launch lock is still held" >&2
        release_lock_holders TERM
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
    echo "usage: $0 {start|stop|restart|status|install|foreground|reclaim-lock}" >&2
    exit 2
    ;;
esac
