"""Scheduled engine recovery helpers.

Does not change bookmaker parsers, matcher, or arbitrage formulas.
Kolay90 worker close() detaches CDP only; Chrome stays open.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

ENGINE_RESTART_SECONDS = float(os.getenv("ENGINE_RESTART_SECONDS", "600"))
RESTART_FLAG_FILE = Path("runtime/scheduled_restart.json")
TRANSIENT_STATUSES = {"STARTING", "RECOVERING", "STOPPED"}


def restart_due(started_at: float, now: float | None = None, interval: float = ENGINE_RESTART_SECONDS) -> bool:
    current = time.monotonic() if now is None else now
    return current - started_at >= interval


def begin_scheduled_restart() -> None:
    RESTART_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESTART_FLAG_FILE.write_text('{"scheduledRestart": true}\n', encoding="utf-8")


def end_scheduled_restart() -> None:
    if RESTART_FLAG_FILE.exists():
        try:
            RESTART_FLAG_FILE.unlink()
        except OSError:
            RESTART_FLAG_FILE.write_text('{"scheduledRestart": false}\n', encoding="utf-8")


def scheduled_restart_active() -> bool:
    if not RESTART_FLAG_FILE.exists():
        return False
    try:
        text = RESTART_FLAG_FILE.read_text(encoding="utf-8")
    except OSError:
        return False
    return '"scheduledRestart":true' in text.replace(" ", "")


def display_collector_status(status: str | None, scheduled: bool | None = None) -> str:
    """Hide STARTING/STOPPED/RECOVERING only during a scheduled restart."""
    value = status or "STOPPED"
    if (scheduled if scheduled is not None else scheduled_restart_active()) and value in TRANSIENT_STATUSES:
        return "RUNNING"
    return value


def should_replace_snapshot(incoming, previous_count: int, feeds_ready: bool) -> bool:
    """Replace last-good only with a complete, non-empty snapshot."""
    incoming_count = len(incoming or [])
    if incoming_count > 0 and feeds_ready:
        return True
    if previous_count <= 0:
        return incoming_count > 0 or feeds_ready
    return False
