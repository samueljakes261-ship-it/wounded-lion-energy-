#!/usr/bin/env bash
#
# Safe production/VPS reset for ArbScanner.
#
# Detects whichever process manager is already being used for this
# project (systemd, pm2, Docker Compose, Supervisor) and uses IT to
# stop/start the application -- this script does NOT invent a second
# process-management system. If none is detected, it falls back to
# identifying and restarting the project's own python/node processes
# by command line (same conservative approach as scripts/reset-dev.ps1
# on Windows): a process is only touched if its command line contains
# BOTH this project's own path AND a known ArbScanner entrypoint.
#
# Never touches: source code, .venv, node_modules, config templates,
# credentials.json (the encrypted secret store), or *.log files
# (unless --clear-logs is passed explicitly).
#
# Usage:
#   ./scripts/reset-prod.sh [--dry-run] [--skip-restart] [--clear-logs]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DRY_RUN=false
SKIP_RESTART=false
CLEAR_LOGS=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --skip-restart) SKIP_RESTART=true ;;
        --clear-logs) CLEAR_LOGS=true ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--dry-run] [--skip-restart] [--clear-logs]" >&2
            exit 1
            ;;
    esac
done

log() { echo "[reset-prod] $*"; }

run() {
    if $DRY_RUN; then
        log "[dry-run] would run: $*"
    else
        "$@"
    fi
}

PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

log "Project root: $PROJECT_ROOT"
$DRY_RUN && log "DRY RUN -- no processes will be stopped/started and no files will be modified."

# ---------------------------------------------------------------------
# 1. Detect an existing process manager for this project, if any.
# ---------------------------------------------------------------------
PROCESS_MANAGER="none"

if command -v systemctl >/dev/null 2>&1 && systemctl list-units --all 2>/dev/null | grep -qi "arbscanner"; then
    PROCESS_MANAGER="systemd"
elif command -v pm2 >/dev/null 2>&1 && pm2 list 2>/dev/null | grep -qi "arbscanner"; then
    PROCESS_MANAGER="pm2"
elif { [ -f "$PROJECT_ROOT/docker-compose.yml" ] || [ -f "$PROJECT_ROOT/docker-compose.yaml" ]; } && command -v docker >/dev/null 2>&1; then
    PROCESS_MANAGER="docker-compose"
elif command -v supervisorctl >/dev/null 2>&1 && supervisorctl status 2>/dev/null | grep -qi "arbscanner"; then
    PROCESS_MANAGER="supervisor"
fi

log "Detected process manager: $PROCESS_MANAGER"

stop_via_manager() {
    case "$PROCESS_MANAGER" in
        systemd)
            run sudo systemctl stop arbscanner-api arbscanner-engine arbscanner-frontend || true
            ;;
        pm2)
            run pm2 stop arbscanner-api arbscanner-engine arbscanner-frontend || true
            ;;
        docker-compose)
            run docker compose down
            ;;
        supervisor)
            run sudo supervisorctl stop "arbscanner:" || true
            ;;
    esac
}

start_via_manager() {
    case "$PROCESS_MANAGER" in
        systemd)
            run sudo systemctl start arbscanner-api arbscanner-engine arbscanner-frontend
            ;;
        pm2)
            run pm2 start arbscanner-api arbscanner-engine arbscanner-frontend
            ;;
        docker-compose)
            run docker compose up -d
            ;;
        supervisor)
            run sudo supervisorctl start "arbscanner:"
            ;;
    esac
}

# ---------------------------------------------------------------------
# Fallback: identify this project's own python/node processes by
# command line. Only matches a process whose cmdline contains BOTH
# this project's path AND a known entrypoint -- never touches
# unrelated processes on the host.
# ---------------------------------------------------------------------
find_fallback_pids() {
    pgrep -f "$PROJECT_ROOT" 2>/dev/null | while read -r pid; do
        cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
        case "$cmd" in
            *uvicorn*api:app*|*run_engine.py*|*"npm run dev"*|*vite*)
                echo "$pid"
                ;;
        esac
    done
}

stop_fallback() {
    local pids
    pids="$(find_fallback_pids || true)"

    if [ -z "$pids" ]; then
        log "No matching ArbScanner processes found."
        return
    fi

    for pid in $pids; do
        if $DRY_RUN; then
            log "[dry-run] would stop PID $pid"
        else
            log "Stopping PID $pid"
            kill "$pid" 2>/dev/null || true
        fi
    done

    if ! $DRY_RUN; then
        sleep 2
    fi
}

if [ "$PROCESS_MANAGER" != "none" ]; then
    stop_via_manager
else
    stop_fallback
fi

# ---------------------------------------------------------------------
# 2. Clear disposable runtime/cache state (never credentials.json).
# ---------------------------------------------------------------------
DISPOSABLE_PATHS=(
    "runtime/credentials_state.json"
    "cached_opportunities.json"
    "cached_status.json"
    "cached_status.json.tmp"
    "cached_opportunities.json.tmp"
    "output"
)

for path in "${DISPOSABLE_PATHS[@]}"; do
    full="$PROJECT_ROOT/$path"
    if [ -e "$full" ]; then
        if $DRY_RUN; then
            log "[dry-run] would clear $path"
        else
            log "Clearing $path"
            rm -rf "$full"
        fi
    fi
done

if $CLEAR_LOGS; then
    while IFS= read -r f; do
        if $DRY_RUN; then
            log "[dry-run] would delete log $f"
        else
            log "Deleting log $f"
            rm -f "$f"
        fi
    done < <(find "$PROJECT_ROOT" -maxdepth 3 -name "*.log" 2>/dev/null)
fi

# ---------------------------------------------------------------------
# 3. Reset in-memory/persisted credential health state.
#    Never touches credentials.json (the encrypted secrets).
# ---------------------------------------------------------------------
if $DRY_RUN; then
    log "[dry-run] would run: $PYTHON_BIN -m credentials.cli reset-state"
else
    "$PYTHON_BIN" -m credentials.cli reset-state || true
fi

if $SKIP_RESTART; then
    log "--skip-restart set -- not restarting the application."
    exit 0
fi

# ---------------------------------------------------------------------
# 4. Restart.
# ---------------------------------------------------------------------
if $DRY_RUN; then
    log "[dry-run] would restart via: $PROCESS_MANAGER (or a direct fallback start if none detected)"
    log "Dry run complete -- no changes were made."
    exit 0
fi

if [ "$PROCESS_MANAGER" != "none" ]; then
    start_via_manager
else
    log "No process manager detected -- starting components directly (nohup)."
    log "For a real VPS deployment, prefer a systemd/pm2/Docker/Supervisor unit instead of this fallback."

    mkdir -p "$PROJECT_ROOT/logs"

    nohup "$PYTHON_BIN" -m uvicorn api:app --host 0.0.0.0 --port 8000 \
        >> "$PROJECT_ROOT/logs/api.log" 2>&1 &
    nohup "$PYTHON_BIN" -u run_engine.py \
        >> "$PROJECT_ROOT/logs/engine.log" 2>&1 &

    if [ -d "$PROJECT_ROOT/frontend" ]; then
        (cd "$PROJECT_ROOT/frontend" && nohup npm run dev \
            >> "$PROJECT_ROOT/logs/frontend.log" 2>&1 &)
    fi
fi

sleep 5

# ---------------------------------------------------------------------
# 5. Health checks + report.
# ---------------------------------------------------------------------
log "Credential health check (provider=zenrows):"
"$PYTHON_BIN" -m credentials.cli health --provider zenrows || true

if command -v curl >/dev/null 2>&1 && curl -fsS -o /dev/null --max-time 5 "http://localhost:8000/opportunities"; then
    log "RESULT: API responded on port 8000. Restart succeeded."
else
    log "RESULT: API did not respond within the check window. Check logs/api.log (or your process manager's logs)."
fi
