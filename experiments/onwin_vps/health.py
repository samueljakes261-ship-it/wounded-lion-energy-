"""Tell process health apart from odds freshness for the Onwin VPS collector.

The engine used to read a missing ZenRows worker as stopped once the
snapshot file aged out. The Chrome collector can be attached and quiet
at the same time. Quiet odds stay out of the matcher. The dashboard
hears that the process is waiting, not that it has exited.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = ROOT / "experiments" / "onwin_vps" / "output" / "status.json"

# A status file older than this means the collector loop is not running.
# One slow response read must not look like a dead process.
PROCESS_HEARTBEAT_SECONDS = 45.0


def dashboard_status(
    *,
    phase: str,
    attached: bool,
    chrome_listening: bool,
    challenge: bool,
    snapshot_age: float | None,
    max_age: float,
) -> str:
    """Dashboard word for one lane while the collector process is alive."""
    if challenge:
        return "ERROR"
    if not attached and not chrome_listening:
        return "RECOVERING"
    if snapshot_age is not None and 0 <= snapshot_age <= max_age:
        return "RUNNING"
    if attached and phase == "watching":
        return "WAITING_FOR_DATA"
    if chrome_listening or phase in {"attaching", "starting"}:
        return "STARTING"
    return "RECOVERING"


def dashboard_error(*, challenge: bool, status: str, detail: str | None) -> str | None:
    if challenge:
        return "Cloudflare check is on the open tab. It is left alone."
    if status == "WAITING_FOR_DATA":
        return "Collector is attached. No fresh odds in this window."
    if status == "RECOVERING":
        return detail or "Chrome debugging port is down. Reconnecting."
    if status == "STARTING":
        return None
    if status == "ERROR":
        return detail or "Collector error."
    return None


def load_process_status(
    now: float | None = None,
    *,
    path: Path | None = None,
    max_idle: float = PROCESS_HEARTBEAT_SECONDS,
) -> dict | None:
    """The collector's own status file, or None when that process is quiet."""
    current = time.time() if now is None else now
    target = path or STATUS_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    updated = payload.get("updated_at")
    if not isinstance(updated, (int, float)):
        return None
    if current - float(updated) > max_idle or current - float(updated) < -30:
        return None
    return payload


def _snapshot_age(peek, now: datetime) -> float | None:
    del now
    if not peek:
        return None
    age = peek.get("age")
    if not isinstance(age, (int, float)):
        return None
    return float(age)


def apply_vps_collector_status(payload: dict, now: datetime, *, status_path: Path | None = None) -> None:
    """Replace a false stopped/error row when the VPS collector is still up.

    Odds are not made fresh here. snapshot age stays the age of the file.
    A stale file still fails the matcher's freshness check.
    """
    if not isinstance(payload, dict):
        return
    collectors = payload.get("collectors")
    if not isinstance(collectors, dict):
        return
    current = now.timestamp() if hasattr(now, "timestamp") else time.time()
    process = load_process_status(current, path=status_path)
    if process is None:
        return
    from parsers.onwin.prematch_snapshot import peek_stored as peek_prematch
    from parsers.onwin.remote_snapshot import max_age_seconds
    from parsers.onwin.remote_snapshot import peek_stored as peek_live
    from prematch.pipeline import PREMATCH_MAX_ODDS_AGE_SECONDS

    lanes = (
        ("onwin", max_age_seconds(), peek_live(now)),
        ("onwin_prematch", PREMATCH_MAX_ODDS_AGE_SECONDS, peek_prematch(now)),
    )
    phase = str(process.get("phase") or "")
    attached = bool(process.get("attached"))
    listening = bool(process.get("chrome_listening"))
    detail = process.get("last_error")
    detail = str(detail) if detail else None
    for key, max_age, peeked in lanes:
        row = collectors.get(key)
        if not isinstance(row, dict):
            continue
        # A live ZenRows worker reports its own health. Do not paint over it.
        if row.get("workerAlive") and row.get("rawStatus") not in {None, "stopped", "error"}:
            continue
        challenge = bool(process.get("live_challenge")) if key == "onwin" else False
        age = _snapshot_age(peeked, now)
        status = dashboard_status(
            phase=phase,
            attached=attached,
            chrome_listening=listening,
            challenge=challenge,
            snapshot_age=age,
            max_age=max_age,
        )
        updated = dict(row)
        updated["collectorStatus"] = status
        updated["workerAlive"] = True
        updated["rawStatus"] = phase or updated.get("rawStatus")
        updated["error"] = dashboard_error(challenge=challenge, status=status, detail=detail)
        updated["lastError"] = updated["error"]
        if age is not None:
            updated["ageSeconds"] = round(age, 1)
            updated["dataAge"] = round(age, 1)
        if peeked and peeked.get("matches") is not None:
            count = len(peeked["matches"])
            updated["eventsCollected"] = count
            updated["recordsCollected"] = count
        collectors[key] = updated
