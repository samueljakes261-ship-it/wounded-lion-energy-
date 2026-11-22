"""Collect OnWin live odds from the Chrome window Kolay91 already uses.

Attaches to 127.0.0.1:9222, reads the sportsbook responses that page
already makes, and POSTs MatchOdds to the VPS. Does not start ZenRows
and does not close Chrome.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from parsers.onwin.remote_snapshot import match_to_payload
from parsers.onwin.state import OnwinState

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INGEST_URL = "https://api.lintonbeautynrb.org/onwin/live"
DEFAULT_CDP = "http://127.0.0.1:9222"
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
UPDATE_FRAGMENTS = (
    "find_event_snapshots.erisgaming",
    "get_main_line_gap.erisgaming",
)
PID_NAME = "onwin_local_collector.pid"


def _log(message: str) -> None:
    print(f"[ONWIN LOCAL] {message}", flush=True)


def feed_kind(url: str) -> str | None:
    lowered = (url or "").lower()
    if "get_main_line.erisgaming" in lowered:
        return "snapshot"
    if any(fragment in lowered for fragment in UPDATE_FRAGMENTS):
        return "update"
    return None


def unwrap_sports(payload):
    if isinstance(payload, dict) and "sports" in payload:
        return payload
    if isinstance(payload, dict):
        for key in ("result", "data", "payload"):
            inner = payload.get(key)
            found = unwrap_sports(inner)
            if found is not None:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = unwrap_sports(item)
            if found is not None:
                return found
    return None


def _for_onwin_page(request, page) -> bool:
    frame = None
    try:
        frame = request.frame
    except Exception:
        frame = None
    owner = getattr(frame, "page", None) if frame is not None else None
    if owner is not None and owner != page:
        return False
    return "kolay" not in (request.url or "").lower()


def _cdp_url() -> str:
    return (os.environ.get("ONWIN_CDP_URL") or DEFAULT_CDP).strip()


def _page_url() -> str:
    return (os.environ.get("ONWIN_PAGE_URL") or DEFAULT_PAGE).strip()


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


def _release_pid() -> None:
    path = _pid_path()
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def transmit(matches) -> bool:
    import requests

    url = (os.environ.get("ONWIN_INGEST_URL") or DEFAULT_INGEST_URL).strip()
    token = (os.environ.get("ONWIN_INGEST_TOKEN") or "").strip()
    if not token:
        _log("ONWIN_INGEST_TOKEN is required")
        return False
    body = {"matches": [match_to_payload(match) for match in matches]}
    headers = {"Authorization": f"Bearer {token}"}
    delay = 1.0
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=20)
        except requests.RequestException as exc:
            _log(f"VPS unavailable ({type(exc).__name__}); retry {attempt}/3")
        else:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                if payload.get("accepted") is True:
                    _log(
                        f"VPS accepted {payload.get('count')} live odds "
                        f"collected_at={payload.get('collected_at')}"
                    )
                    return True
                _log(f"VPS kept the previous snapshot ({payload.get('reason')})")
                return False
            detail = ""
            try:
                detail = str(response.json().get("detail") or "")
            except ValueError:
                detail = ""
            suffix = f" {detail}" if detail else ""
            _log(f"VPS returned HTTP {response.status_code}{suffix}; retry {attempt}/3")
        time.sleep(delay)
        delay *= 2
    return False


def _attach(cdp_url: str):
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
    except Exception:
        playwright.stop()
        raise
    if not browser.contexts:
        playwright.stop()
        raise RuntimeError("attached Chrome has no window")
    created = False
    for context in browser.contexts:
        for page in context.pages:
            if "onwin" in (page.url or "").lower():
                return playwright, context, page, created
    context = browser.contexts[0]
    return playwright, context, context.new_page(), True


def _release(playwright, page, created: bool) -> None:
    if created and page is not None:
        try:
            page.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / ".env.local", override=True)
    if already_running():
        _log("Collector is already running. Leave that window open.")
        return 0
    _claim_pid()
    state = OnwinState()
    box = {"last_post": 0.0, "saw_snapshot": False}
    playwright = None
    page = None
    created = False

    def publish(force: bool = False) -> None:
        if not state.initialized:
            return
        matches = state.get_match_odds()
        if not matches:
            return
        now = time.time()
        if not force and now - box["last_post"] < 2:
            return
        if transmit(matches):
            box["last_post"] = now

    def on_finished(request):
        try:
            if not _for_onwin_page(request, page):
                return
            kind = feed_kind(request.url)
            if kind is None:
                return
            response = request.response()
            if response is None or response.status >= 400:
                return
            payload = unwrap_sports(json.loads(response.body()))
            if payload is None:
                return
            if kind == "snapshot":
                state.load_initial(payload)
                box["saw_snapshot"] = True
                _log(
                    f"get_main_line events={state.event_count} "
                    f"odds={len(state.get_match_odds())}"
                )
            elif box["saw_snapshot"]:
                changed = state.apply_update(payload)
                if changed:
                    _log(f"update changed_1x2={len(changed)} events={state.event_count}")
            publish()
        except Exception as exc:
            _log(f"response skipped ({type(exc).__name__})")

    try:
        _log(f"Attaching to the Kolay91 Chrome at {_cdp_url()}")
        playwright, context, page, created = _attach(_cdp_url())
    except Exception as exc:
        _log(
            "Could not attach to the Kolay91 Chrome. "
            "Leave that collector running, then start this again."
        )
        _log(type(exc).__name__)
        _release_pid()
        return 2
    try:
        context.on("requestfinished", on_finished)
        if "sportsbook/live" not in (page.url or "").lower():
            _log(f"Opening {_page_url()} in that window")
            try:
                page.goto(_page_url(), wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                _log(f"Navigation did not finish ({type(exc).__name__}). The tab stays open.")
        else:
            _log("Using the Onwin tab already open in that Chrome")
        _log("Watching get_main_line.erisgaming. Ctrl+C stops this collector only.")
        while True:
            page.wait_for_timeout(5000)
            publish(force=time.time() - box["last_post"] >= 10)
    except KeyboardInterrupt:
        _log("Stopped. The Kolay91 Chrome stays open.")
        return 0
    finally:
        _release(playwright, page, created)
        _release_pid()


if __name__ == "__main__":
    sys.exit(main())
