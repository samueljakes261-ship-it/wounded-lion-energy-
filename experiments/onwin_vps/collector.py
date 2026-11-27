"""Onwin collector for a dedicated headless Chrome on the VPS.

Google Chrome is started by experiments/onwin_vps/chrome.sh. This process
attaches to that Chrome the same way the Windows collector attaches to
the Kolay91 window: Playwright connects over the debugging port and does
not launch a browser.

Odds are written straight into the live and prematch snapshot files the
engine already reads. No ingest token and no VNC desktop.

Response bodies are read on the collector loop, never inside a debugger
event. Reading them there stopped the connection after a short burst and
the dashboard returned to error. The open page is left to send its own
traffic. This process does not reload it and does not call the feed
itself. A quiet feed stays unpublished, so old odds are not written out
as new.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from experiments.onwin_vps.book import CollectionBook
from experiments.onwin_vps.listen import (
    KEEP_AWAKE_SECONDS,
    KEEP_AWAKE_SOURCE,
    LaneTap,
    should_keep_awake,
    should_queue_response,
)
from experiments.onwin_vps.safety import OnwinVpsGuardError, validate_target
from parsers.kolay90_prematch.login import is_challenge_text, read_tab_quickly
from parsers.onwin.local_collector import (
    _open_tabs,
    _owner_page,
    feed_kind,
    page_lane,
    PREMATCH_REOPEN_SECONDS,
    resolve_lane,
    should_reload_live,
    should_reload_prematch,
    unwrap_sports,
)
from parsers.onwin.prematch_snapshot import peek_stored as peek_prematch
from parsers.onwin.prematch_snapshot import store_local_snapshot as store_prematch
from parsers.onwin.remote_snapshot import peek_stored as peek_live
from parsers.onwin.remote_snapshot import store_local_snapshot as store_live
from parsers.onwin.state import OnwinState
from parsers.onwin_prematch.parser import parse_prematch

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "experiments" / "onwin_vps" / "output"
DEFAULT_PORT = 9223
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
DEFAULT_PREMATCH_PAGE = "https://onwin4505.com/sportsbook/prelive/main-line/soccer"
LOCK = OUTPUT / "collector.lock"
CHROME_SCRIPT = ROOT / "experiments" / "onwin_vps" / "chrome.sh"


def _log(message: str) -> None:
    print(f"[ONWIN VPS] {message}", flush=True)


def publish_enabled() -> bool:
    """Local snapshot writes are on unless ONWIN_VPS_PUBLISH is explicitly off."""
    raw = os.environ.get("ONWIN_VPS_PUBLISH")
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def cdp_port() -> int:
    raw = (os.environ.get("ONWIN_VPS_CDP_PORT") or str(DEFAULT_PORT)).strip()
    return int(raw)


def cdp_url() -> str:
    explicit = (os.environ.get("ONWIN_VPS_CDP_URL") or "").strip()
    if explicit:
        return explicit
    return f"http://127.0.0.1:{cdp_port()}"


def profile_dir() -> Path:
    raw = (os.environ.get("ONWIN_VPS_CHROME_PROFILE") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "experiments" / "onwin_vps" / "chrome_profile"


def live_page_url() -> str:
    return (os.environ.get("ONWIN_VPS_LIVE_PAGE") or DEFAULT_PAGE).strip()


def prematch_page_url() -> str:
    return (os.environ.get("ONWIN_VPS_PREMATCH_PAGE") or DEFAULT_PREMATCH_PAGE).strip()


def _load_config() -> None:
    path = ROOT / "experiments" / "onwin_vps" / "config.env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _guard() -> None:
    validate_target(cdp_port(), profile_dir())
    if ":9222" in cdp_url():
        raise OnwinVpsGuardError("refusing to attach to port 9222")


_status_written = {"at": 0.0}


def _write_status(book: CollectionBook, force: bool = False) -> None:
    now = time.time()
    if not force and now - _status_written["at"] < 2:
        return
    _status_written["at"] = now
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = book.status(
        publish=publish_enabled(),
        cdp_url=cdp_url(),
        profile=str(profile_dir()),
    )
    path = OUTPUT / "status.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _shape(matches) -> tuple[int, int]:
    events = set()
    markets = set()
    for match in matches:
        events.add((getattr(match, "home_team", ""), getattr(match, "away_team", "")))
        markets.add(getattr(match, "market", "") or "")
    return len(events), len(markets)


def _deliver(matches, label: str) -> bool | None:
    """True when the engine snapshot file was replaced. None when writes are paused."""
    if not publish_enabled():
        _log(f"{label} odds={len(matches)} held locally (ONWIN_VPS_PUBLISH is off)")
        return None
    store = store_live if label == "live" else store_prematch
    try:
        result = store(matches)
    except Exception as exc:
        _log(f"{label} snapshot was not stored ({type(exc).__name__})")
        return False
    if result.get("accepted") is True:
        _log(
            f"stored {result.get('count')} {label} odds "
            f"collected_at={result.get('collected_at')}"
        )
        return True
    _log(f"kept the previous {label} snapshot ({result.get('reason')})")
    return False


def _chrome_listening() -> bool:
    try:
        with urllib.request.urlopen(cdp_url().rstrip("/") + "/json/version", timeout=2) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except Exception:
        return False


# Live odds older than this are not rewritten, so the engine stops using
# them. Three minutes covers a debugger reconnect without serving a book
# that has gone quiet. Prematch odds stay valid for the engine's own
# fifteen-minute window. Rewrites stay inside those windows so one stalled
# Playwright call cannot expire both snapshot files.
LIVE_HOLD_SECONDS = 180.0
PREMATCH_HOLD_SECONDS = 900.0
LIVE_REWRITE_SECONDS = 8.0
PREMATCH_REWRITE_SECONDS = 45.0


def should_refresh_quiet_tab(
    *,
    challenge: bool,
    on_sportsbook: bool,
    seconds_since_response: float,
    seconds_since_refresh: float,
) -> bool:
    """A quiet sportsbook tab stays open.

    Reloading after a silence sent both tabs through Cloudflare. The last
    good odds keep the engine fed until the page sends again.
    """
    del challenge, on_sportsbook, seconds_since_response, seconds_since_refresh
    return False


def live_page_is_challenge(title: str, url: str, text: str = "") -> bool:
    """True when the visible page is a Cloudflare check, not the sportsbook.

    The address bar can still show the sportsbook URL while the document
    says "Just a moment". Reloading then starts the check again.
    """
    if is_challenge_text(title, url):
        return True
    return is_challenge_text(text, "")


def should_open_live_page(
    *,
    live_requests: int,
    seconds_open: float,
    challenge: bool,
    opened: bool,
    readable: bool,
    saw_challenge: bool,
    seconds_since_clear: float,
) -> bool:
    """Do not navigate to a sportsbook tab that is already attached.

    Opening it again restarts Cloudflare. The check has to finish on the
    document that is already showing.
    """
    del live_requests, seconds_open, challenge, opened, readable, saw_challenge, seconds_since_clear
    return False


def should_load_live_page(
    *,
    live_requests: int,
    seconds_since_traffic: float,
    challenge: bool,
    loads: int,
    quiet_reloads: int,
    saw_challenge: bool,
    seconds_since_clear: float,
    max_loads: int = 3,
    max_quiet_reloads: int = 2,
) -> bool:
    """Never reload an attached sportsbook tab.

    A reload starts the Cloudflare check again. The open document is left
    in front, and its responses are captured as the page sends them.
    """
    del (
        live_requests,
        seconds_since_traffic,
        challenge,
        loads,
        quiet_reloads,
        saw_challenge,
        seconds_since_clear,
        max_loads,
        max_quiet_reloads,
    )
    return False


def should_wake_silent_live(
    *,
    live_requests: int,
    seconds_open: float,
    on_sportsbook: bool,
    challenge: bool,
    already_woke: bool,
    minimum_seconds: float = 8,
    wakes: int = 0,
    max_wakes: int = 1,
    gap_seconds: float = 30,
) -> bool:
    """Open a silent sportsbook tab again until it sends a feed.

    The tabs usually fetch get_main_line before the collector is listening.
    Leaving an already-open tab alone then keeps the previous snapshot and
    records no new responses. Live may need more than one open, because the
    first one can be backgrounded before the page subscribes. A Cloudflare
    check is left alone.
    """
    done = wakes if wakes else (1 if already_woke else 0)
    if done >= max_wakes or challenge or not on_sportsbook or live_requests > 0:
        return False
    return seconds_open >= minimum_seconds + done * gap_seconds


def should_republish(*, seconds_since_network: float, hold_seconds: float) -> bool:
    """True while the last good book is still inside its hold window."""
    return 0 <= seconds_since_network <= hold_seconds


def adopt_live_book(state: OnwinState, payload) -> bool:
    """Install a snapshot. Keep the current live 1X2 if the new body has none."""
    trial = OnwinState()
    try:
        trial.load_initial(payload)
    except Exception:
        return False
    current = state.get_match_odds()
    incoming = trial.get_match_odds()
    if current and not incoming:
        if trial.event_count:
            state.apply_update(payload)
        return False
    state._events = trial._events
    state.last_version = trial.last_version
    state.initialized = trial.initialized
    return bool(incoming) or state.event_count > 0


# A listening port that still refuses a client is a wedged debugger.
# One blip reattaches. Several failures in a row mean Chrome has to be
# started again or the collector sits in "starting" with no responses.
ATTACH_FAILURES_BEFORE_RESTART = 4


def needs_chrome_restart(
    error_name: str,
    listening: bool,
    failed_while_listening: int = 0,
) -> bool:
    """Restart Chrome when its port is down, or when attach keeps failing.

    One timeout while port 9223 is open is a dropped debugger client.
    Attach again. Replacing Chrome on that first timeout closed the
    sportsbook session and took the port down.
    """
    if not listening:
        return True
    return failed_while_listening >= ATTACH_FAILURES_BEFORE_RESTART


def chrome_log_excerpt(lines: list[str]) -> str:
    """Keep the launch error and drop crashpad noise from a dead Chrome."""
    kept = []
    for line in lines:
        lowered = line.lower()
        if "crashpad" in lowered or "ptrace:" in lowered or "short read" in lowered:
            continue
        text = line.strip()
        if text:
            kept.append(text)
    return " | ".join(kept[-8:])[:800]


def _acquire_lock():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    handle = LOCK.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise OnwinVpsGuardError("another Onwin VPS collector already holds the lock")
    except ImportError:
        # Windows has no fcntl. The VPS service is the intended host.
        pass
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def _disconnect(playwright) -> None:
    """Drop the debugger client. Chrome and its tabs stay open.

    Closing the sportsbook tabs on a dropped debugger threw away the
    session that had already cleared Cloudflare and was sending odds.
    """
    if playwright is None:
        return
    try:
        playwright.stop()
    except Exception:
        pass


def _short(page, timeout_ms: int, action):
    setter = getattr(page, "set_default_timeout", None)
    try:
        if setter is not None:
            setter(timeout_ms)
        return action()
    except Exception:
        return None
    finally:
        if setter is not None:
            try:
                setter(30000)
            except Exception:
                pass


def read_captured_body(session, request_id: str):
    """Read one finished response on the collector loop.

    Called only from the loop. A debugger event must not call this.
    The event would wait on the same connection it is running on, and
    the live feed would stop.
    """
    result = session.send("Network.getResponseBody", {"requestId": request_id})
    body = result.get("body") or ""
    if result.get("base64Encoded"):
        body = base64.b64decode(body)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if not body:
        return None
    return json.loads(body)


def _hold_focus(session) -> None:
    """Keep Chrome from treating the live tab as hidden.

    Raising the tab on a timer counted as a focus change. The sportsbook
    then stopped its live poll. Focus is held on the debugger session
    that is already attached to the open page.
    """
    if session is None:
        return
    for method, params in (
        ("Emulation.setFocusEmulationOverride", {"focus": True}),
        ("Emulation.setIdleOverride", {"isUserActive": True, "isScreenUnlocked": True}),
        ("Page.setWebLifecycleState", {"state": "active"}),
    ):
        try:
            session.send(method, params)
        except Exception:
            pass


def _page_text(page) -> str:
    text = _short(
        page,
        1500,
        lambda: page.evaluate(
            "() => (document.body && document.body.innerText || '').slice(0, 500)"
        ),
    )
    return text or ""


def _goto(page, url: str, label: str, wait_until: str = "domcontentloaded", timeout: int = 60000) -> None:
    _log(f"Opening {label} {url}")
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
    except Exception as exc:
        _log(f"{label} navigation did not finish ({type(exc).__name__}). The tab stays open.")


def _payload_key(url: str, raw) -> str:
    """Identity of one feed body.

    A short prefix treated two different live updates as the same body
    and dropped the second. The full body is hashed so only a real
    repeat is recognized, and that repeat still refreshes the book.
    """
    try:
        blob = json.dumps(raw, default=str, separators=(",", ":"))
    except Exception:
        blob = ""
    digest = hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()
    return _safe_path(url) + "|" + digest


def _safe_path(url: str) -> str:
    return (url or "").split("?", 1)[0][-160:]


def _refresh(page, url: str, label: str) -> None:
    """Leave an open tab alone. Navigate only a blank tab created this run.

    A tab that already has a document, including one on Cloudflare or one
    whose address left the sportsbook, is not opened again. Doing that
    after the feed had started was putting the live page back on
    "Just a moment..." and the dashboard returned to error.
    """
    read = read_tab_quickly(page)
    if read is None:
        _log(f"{label} tab is still loading. Leaving it open.")
        return
    _title, page_url = read
    if page_url and not page_url.lower().startswith("about:"):
        _log(f"{label} tab is already on the sportsbook. Leaving it open.")
        return
    _goto(page, url, label)


def _pages_loaded(live_url: str, prematch_url: str) -> bool:
    live = (live_url or "").lower()
    prematch = (prematch_url or "").lower()
    return "sportsbook/live" in live and "sportsbook/prelive" in prematch


def run_forever(book: CollectionBook | None = None) -> int:
    _load_config()
    _guard()
    book = book or CollectionBook()
    lock = _acquire_lock()
    state = OnwinState()
    saw_live = {"ok": False}
    prematch = {"matches": [], "last_post": 0.0}
    live_post = {"last": 0.0}
    publish_lock = threading.Lock()
    held = {"live": [], "prematch": [], "live_at": 0.0, "prematch_at": 0.0}

    def _seed_lane(lane: str, peeked, hold_seconds: float) -> None:
        if not peeked:
            return
        age = float(peeked.get("age") or 0)
        matches = peeked.get("matches") or []
        if age < -30 or age > hold_seconds or not matches:
            return
        held[lane] = list(matches)
        held[lane + "_at"] = time.time() - max(age, 0.0)
        _log(f"kept {len(matches)} stored {lane} odds from {age:.0f}s ago")

    try:
        _seed_lane("live", peek_live(), LIVE_HOLD_SECONDS)
        _seed_lane("prematch", peek_prematch(), PREMATCH_HOLD_SECONDS)
    except Exception as exc:
        _log(f"stored odds were not reloaded ({type(exc).__name__})")
    if held["prematch"]:
        prematch["matches"] = list(held["prematch"])

    def remember(lane: str, matches) -> None:
        if not matches:
            return
        with publish_lock:
            held[lane] = list(matches)
            held[lane + "_at"] = time.time()

    def publish_live(from_network: bool = True, heartbeat: bool = False) -> None:
        with publish_lock:
            matches = list(held["live"])
            seen = held["live_at"]
            now = time.time()
            if not matches:
                return
            if heartbeat or not from_network:
                if not should_republish(
                    seconds_since_network=now - seen,
                    hold_seconds=LIVE_HOLD_SECONDS,
                ):
                    return
                if now - live_post["last"] < LIVE_REWRITE_SECONDS:
                    return
            elif now - live_post["last"] < 2:
                return
            started = time.perf_counter()
            published = _deliver(matches, "live")
            events, markets = _shape(matches)
            book.note_odds(
                "live",
                len(matches),
                events=events,
                markets=markets,
                publish_ok=published,
                poll_ms=(time.perf_counter() - started) * 1000,
                from_network=from_network,
            )
            if published is not False:
                live_post["last"] = now
            _write_status(book, force=True)

    def publish_prematch(from_network: bool = True, heartbeat: bool = False) -> None:
        with publish_lock:
            matches = list(held["prematch"])
            seen = held["prematch_at"]
            now = time.time()
            if not matches:
                return
            if heartbeat or not from_network:
                if not should_republish(
                    seconds_since_network=now - seen,
                    hold_seconds=PREMATCH_HOLD_SECONDS,
                ):
                    return
                if now - prematch["last_post"] < PREMATCH_REWRITE_SECONDS:
                    return
            elif now - prematch["last_post"] < 2:
                return
            started = time.perf_counter()
            published = _deliver(matches, "prematch")
            events, markets = _shape(matches)
            book.note_odds(
                "prematch",
                len(matches),
                events=events,
                markets=markets,
                publish_ok=published,
                poll_ms=(time.perf_counter() - started) * 1000,
                from_network=from_network,
            )
            if published is not False:
                prematch["last_post"] = now
            _write_status(book, force=True)

    def republish() -> None:
        """Leave the snapshot files alone between captured responses.

        Rewriting them on a timer moved collected_at forward with no new
        odds, so the engine treated a quiet book as fresh. Playwright
        also cannot share this thread with another writer.
        """
        return

    seen_payloads: set[str] = set()

    def _note_feed_url(url: str) -> None:
        lowered = (url or "").lower()
        if "erisgaming" in lowered or "4297.lol" in lowered:
            book.note_api(_safe_path(url))

    def apply_captured(url: str, raw, lane: str, kind: str | None = None) -> None:
        kind = kind or feed_kind(url)
        if kind is None:
            _note_feed_url(url)
            _write_status(book)
            return
        key = _payload_key(url, raw)
        if key in seen_payloads:
            # The same body still proves the feed is alive. Refresh the
            # snapshot the engine reads, or thirty quiet seconds become
            # an error even though the page answered.
            book.note_response()
            book.note_traffic(kind, lane or "live")
            fresh = lane or "live"
            if held.get(fresh):
                remember(fresh, held[fresh])
                if fresh == "live":
                    publish_live(from_network=True)
                else:
                    publish_prematch(from_network=True)
            else:
                _write_status(book)
            return
        seen_payloads.add(key)
        if len(seen_payloads) > 4000:
            seen_payloads.clear()
        _note_feed_url(url)
        payload = unwrap_sports(raw)
        if payload is None:
            if kind == "snapshot" and isinstance(raw, dict):
                _log(
                    "snapshot body had no sports tree "
                    f"keys={sorted(raw)[:8]} path={_safe_path(url)}"
                )
            book.note_traffic(kind, lane)
            fresh = lane or "live"
            if held.get(fresh):
                book.note_response()
                remember(fresh, held[fresh])
                if fresh == "live":
                    publish_live(from_network=True)
                else:
                    publish_prematch(from_network=True)
            else:
                _write_status(book)
            return
        book.note_response()
        lane = resolve_lane(lane, kind, payload)
        book.note_traffic(kind, lane)
        if lane == "prematch" and kind == "snapshot":
            matches = parse_prematch(payload)
            if not matches:
                _log(f"prematch snapshot had no 1X2 rows path={_safe_path(url)}")
                _write_status(book)
                return
            prematch["matches"] = matches
            remember("prematch", matches)
            publish_prematch(from_network=True)
            return
        if lane != "live":
            _write_status(book)
            return
        if kind == "snapshot" or not saw_live["ok"]:
            if kind == "snapshot":
                adopted = adopt_live_book(state, payload)
            else:
                state.apply_update(payload)
                if state.event_count:
                    state.initialized = True
                adopted = state.event_count > 0
            saw_live["ok"] = state.initialized and (
                state.event_count > 0 or bool(held["live"])
            )
            odds = state.get_match_odds()
            _log(
                f"snapshot events={state.event_count} odds={len(odds)} "
                f"replaced={adopted} path={_safe_path(url)}"
            )
            if odds:
                remember("live", odds)
                publish_live(from_network=True)
            else:
                _write_status(book)
            return
        changed = state.apply_update(payload)
        odds = state.get_match_odds()
        if odds:
            remember("live", odds)
            if changed:
                _log(f"update changed_1x2={len(changed)} events={state.event_count}")
            publish_live(from_network=True)
        else:
            _write_status(book)

    from playwright.sync_api import sync_playwright

    last_chrome_restart = 0.0
    attach_failures = 0
    try:
        while True:
            playwright = None
            created: list = []
            failed = False
            try:
                republish()
                book.chrome_listening = _chrome_listening()
                book.phase = "attaching"
                book.attached = False
                _write_status(book, force=True)
                if not book.chrome_listening:
                    raise RuntimeError("cdp down")
                _log(f"Attaching to dedicated Chrome at {cdp_url()}")
                playwright = sync_playwright().start()
                browser = playwright.chromium.connect_over_cdp(cdp_url(), timeout=20000)
                if not browser.contexts:
                    raise RuntimeError("Chrome has no window")
                context, live_page, prematch_page, created = _open_tabs(browser)
                book.attached = True
                book.chrome_listening = True
                book.last_error = None
                book.phase = "attaching"
                book.live_page = live_page.url or ""
                book.prematch_page = prematch_page.url or ""
                _write_status(book)

                taps = {"live": LaneTap(), "prematch": LaneTap()}
                sessions = {"live": None, "prematch": None}
                fallback: list = []

                def _arm_cdp(page, lane_name: str):
                    """Remember response ids. Do not read bodies here."""
                    tap = taps[lane_name]
                    try:
                        session = page.context.new_cdp_session(page)
                        session.send(
                            "Network.enable",
                            {
                                "maxTotalBufferSize": 100 * 1024 * 1024,
                                "maxResourceBufferSize": 50 * 1024 * 1024,
                            },
                        )
                        try:
                            session.send("Page.enable")
                        except Exception:
                            pass
                    except Exception as exc:
                        _log(f"{lane_name} network listen was not attached ({type(exc).__name__}).")
                        return None

                    def request_will_be_sent(params):
                        request = params.get("request") or {}
                        post = request.get("postData")
                        tap.note_request(
                            str(params.get("requestId") or ""),
                            str(request.get("url") or ""),
                            str(request.get("method") or "GET"),
                            request.get("headers") or {},
                            post if isinstance(post, str) else None,
                        )

                    def response_received(params):
                        response = params.get("response") or {}
                        tap.note_response(
                            str(params.get("requestId") or ""),
                            str(response.get("url") or ""),
                            int(response.get("status") or 0),
                        )

                    def loading_finished(params):
                        tap.note_finished(str(params.get("requestId") or ""))

                    def socket_frame(params):
                        response = params.get("response") or {}
                        payload = response.get("payloadData")
                        if isinstance(payload, str):
                            tap.note_socket(payload)

                    session.on("Network.requestWillBeSent", request_will_be_sent)
                    session.on("Network.responseReceived", response_received)
                    session.on("Network.loadingFinished", loading_finished)
                    session.on("Network.webSocketFrameReceived", socket_frame)
                    if lane_name == "live":
                        _hold_focus(session)
                    return session

                for watched, lane_name in ((live_page, "live"), (prematch_page, "prematch")):
                    sessions[lane_name] = _arm_cdp(watched, lane_name)
                attached = sum(1 for session in sessions.values() if session is not None)
                book.listeners = attached
                _log(f"Capturing responses on {attached} open tabs. Those tabs are not reloaded.")

                def _on_response(response):
                    # Queue only. Reading the body here stalls the debugger.
                    # Context events include the sportsbook frame. The top
                    # document's network session does not.
                    try:
                        url = response.url or ""
                    except Exception:
                        return
                    if not should_queue_response(url):
                        return
                    if len(fallback) >= 40:
                        book.note_queue_dropped(1)
                        del fallback[0]
                    fallback.append(response)

                try:
                    context.on("response", _on_response)
                except Exception:
                    for watched in (live_page, prematch_page):
                        try:
                            watched.on("response", _on_response)
                        except Exception:
                            pass

                def drain_tap(lane_name: str) -> None:
                    session = sessions.get(lane_name)
                    tap = taps[lane_name]
                    if session is not None:
                        for request_id in tap.bodies_needed():
                            try:
                                result = session.send(
                                    "Network.getRequestPostData",
                                    {"requestId": request_id},
                                )
                            except Exception:
                                tap.restore_body_request(request_id)
                                continue
                            tap.set_post_data(request_id, (result or {}).get("postData"))
                    for item in tap.take_ready():
                        try:
                            if item.get("kind") == "socket":
                                apply_captured(
                                    item["url"],
                                    json.loads(item["payload"]),
                                    lane_name,
                                    kind="update",
                                )
                                continue
                            url = item["url"]
                            status = int(item.get("status") or 0)
                            kind = feed_kind(url)
                            if kind is None or status >= 400:
                                _note_feed_url(url)
                                if kind is not None:
                                    book.note_traffic(kind, lane_name)
                                    _write_status(book)
                                continue
                            if session is None:
                                continue
                            raw = read_captured_body(session, item["id"])
                            if raw is None:
                                continue
                            apply_captured(url, raw, lane_name)
                        except Exception as exc:
                            book.last_error = type(exc).__name__
                            book.note_body_failure()
                            _log(f"response skipped ({type(exc).__name__})")

                def drain_fallback() -> None:
                    if not fallback:
                        return
                    batch = fallback[:]
                    fallback.clear()
                    for response in batch:
                        try:
                            url = response.url or ""
                            kind = feed_kind(url)
                            if kind is None:
                                _note_feed_url(url)
                                continue
                            owner = _owner_page(response.request)
                            lane_name = page_lane(owner, live_page, prematch_page) or "live"
                            if response.status >= 400:
                                book.note_traffic(kind, lane_name)
                                _write_status(book)
                                continue
                            apply_captured(url, json.loads(response.body()), lane_name)
                        except Exception as exc:
                            book.last_error = type(exc).__name__
                            book.note_body_failure()
                            _log(f"response skipped ({type(exc).__name__})")

                def read_live_tab():
                    live_read = read_tab_quickly(live_page)
                    live_title = live_read[0] if live_read else ""
                    live_url = live_read[1] if live_read else book.live_page
                    live_text = ""
                    if live_read and not is_challenge_text(live_title, live_url) and book.live_requests == 0:
                        live_text = _page_text(live_page)
                    challenge = bool(live_read) and live_page_is_challenge(live_title, live_url, live_text)
                    if live_read is None:
                        book.live_challenge = True if quiet["saw_challenge"] else book.live_challenge
                    else:
                        book.live_title = live_title
                        book.live_challenge = challenge
                    return live_read is not None, challenge, live_title

                def poke_live(now: float, readable: bool, challenge: bool) -> None:
                    blocked = challenge or not readable
                    if should_keep_awake(
                        challenge=blocked,
                        seconds_since_awake=now - quiet["last_awake"],
                    ):
                        quiet["last_awake"] = now
                        _hold_focus(sessions.get("live"))
                        try:
                            live_page.set_default_timeout(1500)
                            live_page.evaluate(KEEP_AWAKE_SOURCE)
                            for frame in list(live_page.frames):
                                frame_url = (getattr(frame, "url", "") or "").lower()
                                if "sportsbook" not in frame_url and "erisgaming" not in frame_url:
                                    continue
                                try:
                                    frame.evaluate(KEEP_AWAKE_SOURCE)
                                except Exception:
                                    pass
                        except Exception as exc:
                            _log(f"live tab was not marked visible ({type(exc).__name__})")
                        finally:
                            try:
                                live_page.set_default_timeout(20000)
                            except Exception:
                                pass

                try:
                    live_page.set_default_timeout(20000)
                    prematch_page.set_default_timeout(20000)
                except Exception:
                    pass
                _refresh(live_page, live_page_url(), "live")
                book.live_page = live_page.url or ""
                _write_status(book)
                _refresh(prematch_page, prematch_page_url(), "prematch")
                book.live_page = live_page.url or ""
                book.prematch_page = prematch_page.url or ""
                book.page_loaded = _pages_loaded(book.live_page, book.prematch_page)
                book.phase = "watching"
                book.last_error = None
                attach_failures = 0
                try:
                    live_page.bring_to_front()
                except Exception:
                    pass
                _hold_focus(sessions.get("live"))
                _write_status(book, force=True)
                _log("Watching get_main_line.erisgaming. Ctrl+C stops only this collector.")
                _log(f"tabs={len(context.pages)} live={book.live_page}")
                _log(f"prematch tab {book.prematch_page}")
                _log(
                    "The live tab is not reloaded. Responses are read as the open "
                    "page sends them. This collector does not call the feed."
                )
                last_heartbeat = time.time()
                watching_since = last_heartbeat
                blips = {"n": 0}
                quiet = {
                    "seen_responses": book.responses_received,
                    "last_traffic": watching_since,
                    "saw_challenge": False,
                    "last_awake": 0.0,
                    "last_replay": 0.0,
                    "last_title": 0.0,
                    "prefer_snapshot": False,
                    "readable": False,
                }
                while True:
                    republish()
                    try:
                        live_page.wait_for_timeout(500)
                    except Exception as exc:
                        blips["n"] += 1
                        book.last_error = type(exc).__name__
                        if blips["n"] >= 3 or not _chrome_listening():
                            raise
                        _log(
                            f"debugger blip ({type(exc).__name__}). "
                            "Odds stay published. Chrome stays open."
                        )
                        continue
                    try:
                        book.live_page = live_page.url or ""
                        book.prematch_page = prematch_page.url or ""
                        book.page_loaded = _pages_loaded(book.live_page, book.prematch_page)
                        book.chrome_listening = True
                        book.attached = True
                        blips["n"] = 0
                    except Exception as exc:
                        blips["n"] += 1
                        book.last_error = type(exc).__name__
                        if blips["n"] >= 3 or not _chrome_listening():
                            raise
                        _log(
                            f"tab read failed ({type(exc).__name__}). "
                            "Odds stay published. Chrome stays open."
                        )
                        continue
                    drain_tap("live")
                    drain_tap("prematch")
                    drain_fallback()
                    book.queue_dropped = taps["live"].dropped + taps["prematch"].dropped
                    now = time.time()
                    if book.responses_received != quiet["seen_responses"]:
                        quiet["seen_responses"] = book.responses_received
                        quiet["last_traffic"] = now
                    if now - quiet["last_title"] >= KEEP_AWAKE_SECONDS:
                        readable, challenge, _title = read_live_tab()
                        quiet["readable"] = readable
                        quiet["last_title"] = now
                        if challenge:
                            first_challenge = not quiet["saw_challenge"]
                            quiet["saw_challenge"] = True
                            if first_challenge:
                                _log(
                                    "Cloudflare check is on the live tab. "
                                    "Leaving that page in front until it renders."
                                )
                    poke_live(now, quiet["readable"], book.live_challenge is True)
                    if now - last_heartbeat >= 30:
                        last_heartbeat = now
                        readable, challenge, title = read_live_tab()
                        quiet["readable"] = readable
                        quiet["last_title"] = now
                        _log(
                            f"still watching api_seen={book.api_seen} "
                            f"get_main_line={book.snapshots_seen} "
                            f"updates={book.updates_seen} "
                            f"last_api={book.last_api_path} title={title!r} "
                            f"live={book.live_page}"
                        )
                        if not readable:
                            _log("Live tab title was not read. Leaving it open.")
                        elif challenge:
                            _log("Cloudflare check is on the live tab. Waiting for it to finish. Not reloading.")
                        elif should_reload_live(title, book.live_page):
                            _log("Live tab left the sportsbook. Leaving it. Not reloading.")
                        prematch_read = read_tab_quickly(prematch_page)
                        if prematch_read is None:
                            _log("Prematch tab title was not read. Leaving it open.")
                        elif is_challenge_text(prematch_read[0], prematch_read[1]):
                            _log("Cloudflare check is on the prematch tab. Leaving it. Not reloading.")
                        elif should_reload_prematch(prematch_read[0], book.prematch_page):
                            _log("Prematch tab left prelive. Leaving it. Not reloading.")
                    _write_status(book)
            except KeyboardInterrupt:
                _log("Stopped. The dedicated Chrome stays open.")
                _disconnect(playwright)
                return 0
            except Exception as exc:
                failed = True
                book.attached = False
                book.chrome_listening = _chrome_listening()
                book.recovery_attempts += 1
                book.last_disconnect = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if book.chrome_listening:
                    attach_failures += 1
                else:
                    attach_failures = 0
                detail = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:200]
                book.last_error = detail
                _write_status(book, force=True)
                _log(f"Chrome attach failed ({detail}).")
                live_post["last"] = 0.0
                prematch["last_post"] = 0.0
                republish()
            finally:
                if failed:
                    _disconnect(playwright)
            if not failed:
                continue
            delay = 3
            restart = needs_chrome_restart(
                book.last_error or "",
                book.chrome_listening,
                attach_failures,
            )
            if not restart:
                _log("Chrome is still listening on port 9223. Attaching again.")
            elif time.time() - last_chrome_restart > 180:
                attach_failures = 0
                last_chrome_restart = time.time()
                if book.chrome_listening:
                    _log(
                        "Chrome answers on port 9223 but the collector cannot attach. "
                        "Restarting the Onwin Chrome only."
                    )
                else:
                    _log("Chrome's debugging port is down. Restarting the Onwin Chrome only.")
                try:
                    completed = subprocess.run(
                        [str(CHROME_SCRIPT), "restart"],
                        cwd=str(ROOT),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=90,
                    )
                except subprocess.TimeoutExpired as exc:
                    chrome_output = f"{exc.stdout or ''}{exc.stderr or ''}".strip()
                    if chrome_output:
                        _log(chrome_output)
                    _log("chrome.sh restart timed out")
                    book.last_error = "chrome did not start"
                    _write_status(book)
                    time.sleep(180)
                    continue
                chrome_output = f"{completed.stdout or ''}{completed.stderr or ''}".strip()
                if chrome_output:
                    _log(chrome_output)
                _log(f"chrome.sh restart exited {completed.returncode}")
                if completed.returncode != 0:
                    log_path = OUTPUT / "chrome.log"
                    if log_path.is_file():
                        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
                        excerpt = chrome_log_excerpt(lines)
                        if excerpt:
                            _log("chrome.log: " + excerpt)
                    book.last_error = "chrome did not start"
                    _write_status(book)
                    delay = 30
                else:
                    delay = 5
            time.sleep(delay)
    finally:
        try:
            lock.close()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        return run_forever()
    except OnwinVpsGuardError as exc:
        _log(str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
