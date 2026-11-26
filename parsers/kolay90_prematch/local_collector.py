"""Run the Kolay90 prematch collector on this PC and POST odds to the VPS.

Chrome stays on 127.0.0.1. Cookies and the browser profile never leave
this machine. The VPS receives MatchOdds fields only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from parsers.kolay90_prematch.feed import Kolay90PrematchFeed
from parsers.kolay90_prematch.session_state import AUTH_REQUIRED
from parsers.kolay90_prematch.snapshot import match_to_payload
from parsers.kolay90_prematch.vnc_session import (
    chrome_argv,
    chrome_profile_dir,
    cdp_port,
    find_chrome,
    port_open,
    prepare_profile,
)

ROOT = Path(__file__).resolve().parents[2]
AUTH_WAIT_SECONDS = 60.0
PID_NAME = "kolay90_local_collector.pid"


def _log(message: str) -> None:
    print(f"[KOLAY90 LOCAL] {message}", flush=True)


def _pid_path() -> Path:
    return ROOT / "runtime" / PID_NAME


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def already_running() -> bool:
    path = _pid_path()
    if not path.exists():
        return False
    try:
        pid = int(path.read_text(encoding="utf-8").strip() or "0")
    except ValueError:
        return False
    if pid == os.getpid():
        return False
    return _process_alive(pid)


def _claim_pid() -> None:
    path = _pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _windows_chrome() -> str | None:
    found = find_chrome()
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def ensure_local_chrome() -> None:
    """Open the persistent profile only when port 9222 is down."""
    if port_open("127.0.0.1", cdp_port()):
        _log("Chrome already listening on 127.0.0.1:9222")
        return
    binary = _windows_chrome()
    if not binary:
        raise SystemExit("Google Chrome was not found. Set KOLAY90_CHROME_BIN.")
    profile = prepare_profile(chrome_profile_dir())
    _log(f"Starting Chrome with profile {profile}")
    subprocess.Popen(
        chrome_argv(binary, profile=profile),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if port_open("127.0.0.1", cdp_port()):
            _log("Chrome is ready for manual Cloudflare and Kolay90 login")
            return
        time.sleep(0.4)
    raise SystemExit("Chrome did not open its local debugging port.")


def transmit(matches) -> bool:
    """POST the current odds. Returns True only when the VPS accepts them."""
    url = (os.environ.get("KOLAY90_INGEST_URL") or "").strip()
    token = (os.environ.get("KOLAY90_INGEST_TOKEN") or "").strip()
    if not url or not token:
        _log("KOLAY90_INGEST_URL and KOLAY90_INGEST_TOKEN are required")
        return False
    body = {
        "auth_phase": "AUTHENTICATED",
        "matches": [match_to_payload(match) for match in matches],
    }
    headers = {"Authorization": f"Bearer {token}"}
    delay = 2.0
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=20)
        except requests.RequestException as exc:
            _log(f"Kolay90 post failed ({type(exc).__name__}); retry {attempt}/3")
        else:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                if payload.get("accepted") is True:
                    _log(
                        f"VPS accepted {payload.get('count')} odds "
                        f"collected_at={payload.get('collected_at')}"
                    )
                    return True
                _log(f"VPS kept the previous snapshot ({payload.get('reason')})")
                return False
            _log(f"VPS returned HTTP {response.status_code}; retry {attempt}/3")
        time.sleep(delay)
        delay *= 2
    return False


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / ".env.local", override=True)
    if already_running():
        _log("Collector is already running. Leave that window open.")
        return 0
    _claim_pid()
    poll_interval = float(os.getenv("KOLAY90_PREMATCH_POLL_INTERVAL", "90"))
    ensure_local_chrome()
    feed = Kolay90PrematchFeed()
    _log("Waiting for you to finish Cloudflare and Kolay90 login in that Chrome window")
    while True:
        started = time.monotonic()
        result = feed.poll()
        if result.get("ok") and result.get("authenticated") and result.get("matches"):
            if transmit(result["matches"]):
                _log(
                    f"transmitted events={result.get('total_events')} "
                    f"odds={result.get('one_x_two')}"
                )
            else:
                _log("Collection stayed local. Timestamps were not marked transmitted.")
            wait = poll_interval
        elif result.get("auth_required") or result.get("auth_state") == AUTH_REQUIRED:
            _log("SESSION_EXPIRED. Finish login in the open Chrome window. Collection is paused.")
            wait = AUTH_WAIT_SECONDS
        else:
            _log(f"No authenticated odds this cycle ({result.get('failure') or 'empty'})")
            wait = AUTH_WAIT_SECONDS
        remaining = wait - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        _log("Stopped")
        sys.exit(0)
