#!/usr/bin/env bash
# Start, stop, or inspect the Onwin VPS collector. Chrome is separate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ACTION="${1:-start}"
OUTPUT="$ROOT/experiments/onwin_vps/output"
LOCK="$OUTPUT/collector.lock"
LOG="$OUTPUT/collector.log"
PID_FILE="$OUTPUT/collector.pid"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

ours() {
  local pid="$1"
  local proc="/proc/${pid}/cmdline"
  [ -r "$proc" ] || return 1
  local cmd=""
  cmd="$(tr '\0' ' ' < "$proc" || true)" 2>/dev/null || true
  case "$cmd" in
    *experiments.onwin_vps*) return 0 ;;
    *) return 1 ;;
  esac
}

running_pid() {
  local pid
  pid="$(cat "$LOCK" 2>/dev/null || true)"
  if [ -n "${pid}" ] && ours "$pid"; then
    echo "$pid"
    return 0
  fi
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${pid}" ] && ours "$pid"; then
    echo "$pid"
    return 0
  fi
  return 1
}

case "$ACTION" in
  start)
    if pid="$(running_pid)"; then
      echo "[onwin-vps] collector already running pid ${pid}"
      exit 0
    fi
    mkdir -p "$OUTPUT"
    if [ -f "$ROOT/experiments/onwin_vps/config.env" ]; then
      set -a
      # shellcheck disable=SC1091
      source "$ROOT/experiments/onwin_vps/config.env"
      set +a
    fi
    nohup "$PYTHON" -m experiments.onwin_vps >>"$LOG" 2>&1 &
    echo $! >"$PID_FILE"
    echo "[onwin-vps] collector started pid $(cat "$PID_FILE")"
    echo "[onwin-vps] log ${LOG}"
    ;;
  stop)
    if ! pid="$(running_pid)"; then
      echo "[onwin-vps] collector is not running"
      rm -f "$PID_FILE"
      exit 0
    fi
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
    echo "[onwin-vps] stopped pid ${pid}"
    rm -f "$PID_FILE"
    ;;
  restart)
    "$0" stop
    "$0" start
    ;;
  status)
    "$ROOT/experiments/onwin_vps/chrome.sh" status || true
    if pid="$(running_pid)"; then
      echo "[onwin-vps] collector=running pid ${pid}"
    else
      echo "[onwin-vps] collector=stopped"
    fi
    if [ -f "$OUTPUT/status.json" ]; then
      cat "$OUTPUT/status.json"
      echo
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
