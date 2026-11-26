"""Collect OnWin live and prematch odds from the Kolay91 Chrome.

Attaches to 127.0.0.1:9222. Live stays on the live soccer tab. Prematch
opens a second tab. Odds are posted to the VPS. Does not start ZenRows
and does not close Chrome.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from parsers.kolay90_prematch.login import is_challenge_text, read_tab_quickly
from parsers.onwin.parser import FOOTBALL_SPORT_ID
from parsers.onwin.prematch_snapshot import match_to_payload as prematch_to_payload
from parsers.onwin.remote_snapshot import match_to_payload
from parsers.onwin.state import OnwinState
from parsers.onwin_prematch.parser import FINISHED_STATUSES, parse_prematch

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INGEST_URL = "https://api.lintonbeautynrb.org/onwin/live"
DEFAULT_PREMATCH_URL = "https://api.lintonbeautynrb.org/onwin/prematch"
DEFAULT_CDP = "http://127.0.0.1:9222"
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
DEFAULT_PREMATCH_PAGE = "https://onwin4505.com/sportsbook/prelive/main-line/soccer"
UPDATE_FRAGMENTS = (
    "find_event_snapshots.erisgaming",
    "get_main_line_gap.erisgaming",
)
# After a navigation, leave the tab alone this long. A second goto during
# that window was reloading prelive before get_main_line came back.
PREMATCH_REOPEN_SECONDS = 180.0
PID_NAME = "onwin_local_collector.pid"


def _log(message: str) -> None:
    print(f"[ONWIN LOCAL] {message}", flush=True)


def _left_sportsbook(title: str, page_url: str, marker: str) -> bool:
    """True only when the tab has left the sportsbook.

    A Cloudflare check, including one whose address no longer contains
    the sportsbook path, a blank tab that is still loading, and a tab
    already on that sportsbook stay open. Opening the sportsbook again
    during the check was restarting it.
    """
    if is_challenge_text(title, page_url):
        return False
    url = (page_url or "").lower()
    if not url or url.startswith("about:"):
        return False
    return marker not in url


def should_reload_live(title: str, page_url: str) -> bool:
    return _left_sportsbook(title, page_url, "sportsbook/live")


def should_reload_prematch(title: str, page_url: str) -> bool:
    return _left_sportsbook(title, page_url, "sportsbook/prelive")


def health_url(ingest_url: str) -> str:
    parts = urlsplit(ingest_url or "")
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))


def feed_kind(url: str) -> str | None:
    """Tell a full book apart from a later patch.

    The live site now opens the book with get_main_line_compact. That
    name does not contain get_main_line.erisgaming, so the old check
    counted the response and then dropped it. Gap and find_event_snapshots
    stay updates. They are checked first so get_main_line_gap is not
    treated as the opening book.
    """
    lowered = (url or "").lower()
    if any(fragment in lowered for fragment in UPDATE_FRAGMENTS):
        return "update"
    if (
        "get_main_line_compact.erisgaming" in lowered
        or "get_main_line.erisgaming" in lowered
    ):
        return "snapshot"
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


def snapshot_lane(payload) -> str | None:
    """Tell a full main-line body apart when it has no page frame.

    A live tree is in-progress events. A prematch tree is events that
    have not started. A mix is left undecided so one response cannot
    replace the other feed.
    """
    football = (payload or {}).get("sports", {}).get(FOOTBALL_SPORT_ID) or {}
    live = False
    upcoming = False
    for category in (football.get("categories") or {}).values():
        if not isinstance(category, dict):
            continue
        for tournament in (category.get("tournaments") or {}).values():
            if not isinstance(tournament, dict):
                continue
            events = tournament.get("events") or {}
            if not isinstance(events, dict):
                continue
            for event in events.values():
                if not isinstance(event, dict):
                    continue
                status = str((event.get("diff") or {}).get("status") or "")
                if not status or status in FINISHED_STATUSES:
                    continue
                if status == "in_progress":
                    live = True
                else:
                    upcoming = True
                if live and upcoming:
                    return None
    if live:
        return "live"
    if upcoming:
        return "prematch"
    return None


def _owner_page(request):
    try:
        frame = request.frame
    except Exception:
        return None
    if frame is None:
        return None
    return getattr(frame, "page", None)


def resolve_lane(owner_lane: str, kind: str, payload) -> str:
    """Keep a main-line body when the page wrapper was not one of our tabs.

    A live response whose frame page is a different Playwright wrapper used
    to be dropped. The sports tree still says whether the events are
    in progress. An update with no page stays on the live book, which is
    where gap traffic belongs.
    """
    if owner_lane:
        return owner_lane
    if kind == "snapshot":
        return snapshot_lane(payload) or ""
    if kind == "update":
        return "live"
    return ""


def page_lane(owner, live_page, prematch_page) -> str:
    """Which sportsbook tab sent this response.

    Playwright sometimes hands back a different page wrapper than the one
    saved at attach. The URL still says live or prelive, and that is enough
    to keep a live response from being dropped.
    """
    if owner is None:
        return ""
    if owner is prematch_page:
        return "prematch"
    if owner is live_page:
        return "live"
    try:
        url = (getattr(owner, "url", "") or "").lower()
    except Exception:
        return ""
    if "sportsbook/prelive" in url or "/prematch" in url:
        return "prematch"
    if "sportsbook/live" in url:
        return "live"
    return ""


def _cdp_url() -> str:
    return (os.environ.get("ONWIN_CDP_URL") or DEFAULT_CDP).strip()


def _page_url() -> str:
    return (os.environ.get("ONWIN_PAGE_URL") or DEFAULT_PAGE).strip()


def _prematch_page_url() -> str:
    return (os.environ.get("ONWIN_PREMATCH_PAGE_URL") or DEFAULT_PREMATCH_PAGE).strip()


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


def probe_vps(ingest_url: str) -> bool | None:
    """Ask /health before any odds post.

    A failed post is not the same thing as the VPS being down. None means
    this process has not checked yet.
    """
    import requests

    target = health_url(ingest_url)
    if not target:
        _log("Onwin ingest URL has no host, so VPS health was not checked")
        return False
    try:
        response = requests.get(target, timeout=8)
    except requests.RequestException as exc:
        _log(f"Could not reach the VPS at {target} ({type(exc).__name__})")
        return False
    if response.status_code == 200:
        _log(f"VPS is up ({target})")
        return True
    _log(f"VPS answered {target} with HTTP {response.status_code}")
    return False


def transmit(matches, url: str, label: str, to_payload, *, vps_up: bool | None = None) -> bool:
    import requests

    token = (os.environ.get("ONWIN_INGEST_TOKEN") or "").strip()
    if not token:
        _log("ONWIN_INGEST_TOKEN is required")
        return False
    body = {"matches": [to_payload(match) for match in matches]}
    headers = {"Authorization": f"Bearer {token}"}
    delay = 1.0
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=20)
        except requests.RequestException as exc:
            if vps_up:
                _log(
                    f"VPS is up; {label} post failed ({type(exc).__name__}); "
                    f"retry {attempt}/3"
                )
            else:
                _log(
                    f"Could not reach the VPS for {label} "
                    f"({type(exc).__name__}); retry {attempt}/3"
                )
        else:
            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                if payload.get("accepted") is True:
                    _log(
                        f"VPS accepted {payload.get('count')} {label} odds "
                        f"collected_at={payload.get('collected_at')}"
                    )
                    return True
                _log(f"VPS kept the previous {label} snapshot ({payload.get('reason')})")
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


def _live_ingest_url() -> str:
    return (os.environ.get("ONWIN_INGEST_URL") or DEFAULT_INGEST_URL).strip()


def _prematch_ingest_url() -> str:
    return (os.environ.get("ONWIN_PREMATCH_INGEST_URL") or DEFAULT_PREMATCH_URL).strip()


def _open_tabs(browser):
    """Return (context, live_page, prematch_page, pages_this_run_opened)."""
    context = browser.contexts[0]
    live_page = None
    prematch_page = None
    for page in context.pages:
        url = (page.url or "").lower()
        if "onwin" not in url:
            continue
        if "sportsbook/prelive" in url or "/prematch" in url:
            prematch_page = prematch_page or page
        elif "sportsbook/live" in url:
            live_page = live_page or page
    created = []
    if live_page is None:
        live_page = context.new_page()
        created.append(live_page)
    if prematch_page is None:
        prematch_page = context.new_page()
        created.append(prematch_page)
    return context, live_page, prematch_page, created


def _release(playwright, pages) -> None:
    for page in pages or []:
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
    from playwright.sync_api import sync_playwright

    load_dotenv(ROOT / ".env", override=True)
    load_dotenv(ROOT / ".env.local", override=True)
    if already_running():
        _log("Collector is already running. Leave that window open.")
        return 0
    _claim_pid()
    state = OnwinState()
    box = {"last_post": 0.0, "saw_snapshot": False}
    prematch = {"matches": [], "last_post": 0.0}
    vps_up = probe_vps(_live_ingest_url())
    playwright = None
    created = []
    live_page = None
    prematch_page = None

    def publish_live(force: bool = False) -> None:
        if not state.initialized:
            return
        matches = state.get_match_odds()
        if not matches:
            return
        now = time.time()
        if not force and now - box["last_post"] < 2:
            return
        if transmit(matches, _live_ingest_url(), "live", match_to_payload, vps_up=vps_up):
            box["last_post"] = now

    def publish_prematch(force: bool = False) -> None:
        matches = prematch["matches"]
        if not matches:
            return
        now = time.time()
        if not force and now - prematch["last_post"] < 2:
            return
        if transmit(
            matches,
            _prematch_ingest_url(),
            "prematch",
            prematch_to_payload,
            vps_up=vps_up,
        ):
            prematch["last_post"] = now

    def on_finished(request):
        try:
            if "kolay" in (request.url or "").lower():
                return
            owner = _owner_page(request)
            if owner is not None and owner is not live_page and owner is not prematch_page:
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
            lane = "live"
            if owner is prematch_page:
                lane = "prematch"
            elif owner is None and kind == "snapshot":
                lane = snapshot_lane(payload) or ""
            if lane == "prematch" and kind == "snapshot":
                matches = parse_prematch(payload)
                if matches:
                    prematch["matches"] = matches
                    _log(f"prematch odds={len(matches)}")
                    publish_prematch()
                return
            if lane != "live":
                return
            if kind == "snapshot":
                state.load_initial(payload)
                box["saw_snapshot"] = True
                _log(
                    f"snapshot events={state.event_count} "
                    f"odds={len(state.get_match_odds())}"
                )
            elif not box["saw_snapshot"]:
                state.apply_update(payload)
                if state.event_count:
                    state.initialized = True
                    box["saw_snapshot"] = True
                    _log(
                        f"seeded from update events={state.event_count} "
                        f"odds={len(state.get_match_odds())}"
                    )
            else:
                changed = state.apply_update(payload)
                if changed:
                    _log(f"update changed_1x2={len(changed)} events={state.event_count}")
            publish_live()
        except Exception as exc:
            _log(f"response skipped ({type(exc).__name__})")

    def _goto(page, url: str, label: str) -> None:
        _log(f"Opening {label} {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            _log(f"{label} navigation did not finish ({type(exc).__name__}). The tab stays open.")

    try:
        _log(f"Attaching to the Kolay91 Chrome at {_cdp_url()}")
        playwright = sync_playwright().start()
        browser = playwright.chromium.connect_over_cdp(_cdp_url())
        if not browser.contexts:
            raise RuntimeError("attached Chrome has no window")
        context, live_page, prematch_page, created = _open_tabs(browser)
    except Exception as exc:
        _log(
            "Could not attach to the Kolay91 Chrome. "
            "Leave that collector running, then start this again."
        )
        _log(type(exc).__name__)
        _release(playwright, [])
        _release_pid()
        return 2
    try:
        context.on("requestfinished", on_finished)

        def _open_if_needed(page, url: str, label: str, marker: str) -> None:
            read = read_tab_quickly(page)
            if read is None:
                _log(f"{label} tab is still loading. Leaving it open.")
                return
            title, page_url = read
            if is_challenge_text(title, page_url):
                _log(f"{label} tab is on a Cloudflare check. Leaving it open.")
                return
            if marker in page_url.lower():
                _log(f"Using the Onwin {label} tab already open in that Chrome")
                return
            _goto(page, url, label)

        _open_if_needed(live_page, _page_url(), "live", "sportsbook/live")
        _open_if_needed(prematch_page, _prematch_page_url(), "prematch", "sportsbook/prelive")
        _log("Watching live and prematch get_main_line.erisgaming. Ctrl+C stops this collector only.")
        _log("Prematch stays on the open prelive tab. It is not reloaded on a timer.")
        last_prematch_open = time.time()
        last_tab_check = time.time()
        while True:
            live_page.wait_for_timeout(5000)
            publish_live(force=time.time() - box["last_post"] >= 10)
            publish_prematch(force=time.time() - prematch["last_post"] >= 60)
            now = time.time()
            if now - last_tab_check < 30:
                continue
            last_tab_check = now
            read = read_tab_quickly(prematch_page)
            if read is None:
                _log("Prematch tab is still loading. Leaving it alone.")
                continue
            title, page_url = read
            if (
                should_reload_prematch(title, page_url)
                and now - last_prematch_open >= PREMATCH_REOPEN_SECONDS
            ):
                last_prematch_open = time.time()
                _log("Prematch tab left prelive. Opening it again.")
                _goto(prematch_page, _prematch_page_url(), "prematch")
    except KeyboardInterrupt:
        _log("Stopped. The Kolay91 Chrome stays open.")
        return 0
    finally:
        _release(playwright, created)
        _release_pid()


if __name__ == "__main__":
    sys.exit(main())
