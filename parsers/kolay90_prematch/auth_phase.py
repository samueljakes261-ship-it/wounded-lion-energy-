"""Kolay90 authentication phases. No cookies, tokens, or page bodies."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

NOT_INITIALIZED = "NOT_INITIALIZED"
BROWSER_STARTING = "BROWSER_STARTING"
AWAITING_MANUAL_AUTH = "AWAITING_MANUAL_AUTH"
AUTHENTICATING = "AUTHENTICATING"
AUTHENTICATED = "AUTHENTICATED"
SESSION_EXPIRED = "SESSION_EXPIRED"
AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"

PHASES = (
    NOT_INITIALIZED,
    BROWSER_STARTING,
    AWAITING_MANUAL_AUTH,
    AUTHENTICATING,
    AUTHENTICATED,
    SESSION_EXPIRED,
    AUTHENTICATION_FAILED,
)

MANUAL_INTERVENTION = {
    AWAITING_MANUAL_AUTH,
    SESSION_EXPIRED,
    AUTHENTICATION_FAILED,
}

_MANUAL_PAGES = {"CLOUDFLARE", "AGREEMENT", "LOGIN", "KOLAY90_UNKNOWN", "UNKNOWN"}
_EXPIRED_FAILURES = {
    "login_expired",
    "cloudflare_challenge",
    "cloudflare_html",
    "agreement_page",
    "login_page",
    "authentication_required",
    "http_401",
    "http_403",
    "kolay90_tab_missing",
}
_START_FAILURES = {
    "chrome_missing",
    "vncserver_missing",
    "chrome_cdp_down",
    "vnc_desktop_down",
    "chrome_profile_busy",
}

ROOT = Path(__file__).resolve().parents[2]


def session_record_path() -> Path:
    raw = (os.environ.get("KOLAY90_SESSION_STATUS") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "runtime" / "kolay90_session_status.json"


def derive_auth_phase(
    *,
    browser_listening: bool = False,
    browser_starting: bool = False,
    page_state: str | None = None,
    fetch_authenticated: bool = False,
    fetch_failure: str | None = None,
    previously_authenticated: bool = False,
    fetch_in_progress: bool = False,
) -> str:
    """Map observed evidence to one authentication phase.

    A loaded homepage or an open browser is not authentication.
    AUTHENTICATED requires a successful authenticated getMaclar parse.
    """
    if fetch_authenticated:
        return AUTHENTICATED
    if browser_starting:
        return BROWSER_STARTING
    if fetch_in_progress and browser_listening and page_state not in _MANUAL_PAGES:
        return AUTHENTICATING
    if previously_authenticated and (
        fetch_failure in _EXPIRED_FAILURES or page_state in {"CLOUDFLARE", "AGREEMENT", "LOGIN"}
    ):
        return SESSION_EXPIRED
    if fetch_failure in _START_FAILURES and not browser_listening:
        return AUTHENTICATION_FAILED
    if browser_listening or page_state in _MANUAL_PAGES or fetch_failure in _EXPIRED_FAILURES:
        return AWAITING_MANUAL_AUTH
    if fetch_failure:
        return AUTHENTICATION_FAILED if not previously_authenticated else SESSION_EXPIRED
    return NOT_INITIALIZED


def blank_record(profile: str | None = None) -> dict:
    return {
        "auth_phase": NOT_INITIALIZED,
        "last_authenticated_at": None,
        "last_authenticated_request_at": None,
        "last_auth_error": None,
        "manual_intervention_required": False,
        "browser_profile": profile,
        "browser_process": "down",
        "updated_at": None,
    }


def read_session_record() -> dict:
    path = session_record_path()
    if not path.exists():
        return blank_record()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return blank_record()
    if not isinstance(payload, dict):
        return blank_record()
    record = blank_record(payload.get("browser_profile"))
    phase = payload.get("auth_phase")
    if phase in PHASES:
        record["auth_phase"] = phase
    for key in (
        "last_authenticated_at",
        "last_authenticated_request_at",
        "last_auth_error",
        "browser_process",
        "updated_at",
    ):
        value = payload.get(key)
        if isinstance(value, str) or value is None:
            record[key] = value
    record["manual_intervention_required"] = record["auth_phase"] in MANUAL_INTERVENTION
    return record


def update_session_record(
    *,
    phase: str,
    error: str | None = None,
    profile: str | None = None,
    browser_process: str | None = None,
    authenticated_request: bool = False,
    now: str | None = None,
) -> dict:
    """Persist non-secret session phase data. Refuses cookie-like fields."""
    if phase not in PHASES:
        phase = NOT_INITIALIZED
    current = read_session_record()
    stamp = now or datetime.now(timezone.utc).isoformat()
    record = blank_record(profile or current.get("browser_profile"))
    record["auth_phase"] = phase
    record["last_authenticated_at"] = current.get("last_authenticated_at")
    record["last_authenticated_request_at"] = current.get("last_authenticated_request_at")
    record["browser_process"] = browser_process or current.get("browser_process") or "down"
    record["updated_at"] = stamp
    record["manual_intervention_required"] = phase in MANUAL_INTERVENTION
    record["last_auth_error"] = None if phase == AUTHENTICATED else (error or None)
    if phase == AUTHENTICATED and current.get("auth_phase") != AUTHENTICATED:
        record["last_authenticated_at"] = stamp
    if phase == AUTHENTICATED and authenticated_request:
        record["last_authenticated_request_at"] = stamp
        if not record["last_authenticated_at"]:
            record["last_authenticated_at"] = stamp
    path = session_record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
    return record
