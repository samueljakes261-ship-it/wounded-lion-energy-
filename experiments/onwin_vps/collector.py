"""Onwin collector for a dedicated headless Chrome on the VPS.

Google Chrome is started by experiments/onwin_vps/chrome.sh. This process
attaches to that Chrome the same way the Windows collector attaches to
the Kolay91 window: Playwright connects over the debugging port and does
not launch a browser.

Odds are written straight into the live and prematch snapshot files the
engine already reads. No ingest token and no VNC desktop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from experiments.onwin_vps.book import CollectionBook
from experiments.onwin_vps.safety import OnwinVpsGuardError, validate_target
from parsers.kolay90_prematch.login import is_challenge_text, read_tab_quickly
from parsers.onwin.local_collector import (
    _open_tabs,
    _owner_page,
    feed_kind,
    page_lane,
    PREMATCH_REOPEN_SECONDS,
    should_reload_live,
    should_reload_prematch,
    snapshot_lane,
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


def should_wake_silent_live(
    *,
    live_requests: int,
    seconds_open: float,
    on_sportsbook: bool,
    challenge: bool,
    already_woke: bool,
    minimum_seconds: float = 8,
) -> bool:
    """Reload one sportsbook tab once if it has not sent a feed since we attached.

    The tabs usually fetch get_main_line before the collector is listening.
    Leaving an already-open tab alone then keeps the previous snapshot and
    records no new responses. One reload, after a few seconds with no
    request, is caught by the listener. A Cloudflare check is left alone.
    """
    if already_woke or challenge or not on_sportsbook or live_requests > 0:
        return False
    return seconds_open >= minimum_seconds


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
    """Restart Chrome when its port is down, or when the websocket will not connect.

    One ordinary error while port 9223 is open is a dropped Playwright
    session. Attach again. A TimeoutError from connect_over_cdp means
    /json/version answered and the DevTools websocket did not. That Chrome
    has to be replaced.
    """
    if not listening:
        return True
    # /json/version can answer while the DevTools websocket never accepts
    # a client. That is the stuck Chrome this collector keeps hitting.
    text = error_name or ""
    if "TimeoutError" in text or "connect_over_cdp" in text:
        return failed_while_listening >= 1
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


def _reload_once(page, label: str) -> None:
    """One navigation after a long silence. A timeout leaves the tab open."""
    _log(f"No {label} responses for several minutes. Reloading that tab once.")
    try:
        page.reload(wait_until="commit", timeout=15000)
    except Exception as exc:
        _log(f"{label} reload did not finish ({type(exc).__name__}). The tab stays open.")


def _goto(page, url: str, label: str) -> None:
    _log(f"Opening {label} {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:
        _log(f"{label} navigation did not finish ({type(exc).__name__}). The tab stays open.")


def _safe_path(url: str) -> str:
    return (url or "").split("?", 1)[0][-160:]


def _on_sportsbook(owner, live_page, prematch_page) -> bool:
    if owner is None or owner is live_page or owner is prematch_page:
        return True
    try:
        url = (owner.url or "").lower()
    except Exception:
        return False
    return "onwin" in url or "sportsbook" in url


def _refresh(page, url: str, label: str) -> None:
    """Open a tab that has left the sportsbook. Leave one that is already there.

    A Cloudflare address often no longer contains the sportsbook path.
    Opening that tab again restarts the check. A tab already on the
    sportsbook is also left open so get_main_line can finish.
    """
    marker = "sportsbook/prelive" if label == "prematch" else "sportsbook/live"
    read = read_tab_quickly(page)
    if read is None:
        _log(f"{label} tab is still loading. Leaving it open.")
        return
    title, page_url = read
    if is_challenge_text(title, page_url):
        _log(f"{label} tab is on a Cloudflare check. Leaving it open.")
        return
    if marker in page_url.lower():
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
        """Rewrite the last good book on this thread.

        Playwright's sync client breaks if another thread is running, which
        left the collector at phase starting with responses_received at 0.
        """
        try:
            publish_live(from_network=False, heartbeat=True)
            publish_prematch(from_network=False, heartbeat=True)
        except Exception as exc:
            _log(f"snapshot rewrite skipped ({type(exc).__name__})")

    def on_finished(request, live_page, prematch_page) -> None:
        try:
            url = request.url or ""
            lowered = url.lower()
            if "kolay" in lowered:
                return
            if "erisgaming" in lowered or "4297.lol" in lowered:
                book.note_api(_safe_path(url))
                _write_status(book)
            owner = _owner_page(request)
            if not _on_sportsbook(owner, live_page, prematch_page):
                return
            kind = feed_kind(url)
            if kind is None:
                return
            lane = page_lane(owner, live_page, prematch_page)
            response = request.response()
            if response is None or response.status >= 400:
                book.note_traffic(kind, lane)
                _write_status(book)
                return
            raw = json.loads(response.body())
            payload = unwrap_sports(raw)
            if payload is None:
                if kind == "snapshot" and isinstance(raw, dict):
                    _log(
                        "snapshot body had no sports tree "
                        f"keys={sorted(raw)[:8]} path={_safe_path(url)}"
                    )
                book.note_traffic(kind, lane)
                _write_status(book)
                return
            book.note_response()
            if owner is None and kind == "snapshot":
                lane = snapshot_lane(payload) or ""
            elif owner is None:
                lane = "live"
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
                if odds and (kind == "snapshot" or len(odds) >= len(held["live"])):
                    remember("live", odds)
                    publish_live(from_network=True)
                else:
                    _write_status(book)
                return
            changed = state.apply_update(payload)
            odds = state.get_match_odds()
            if odds and len(odds) >= len(held["live"]):
                remember("live", odds)
            if changed and odds:
                _log(f"update changed_1x2={len(changed)} events={state.event_count}")
                publish_live(from_network=True)
            else:
                _write_status(book)
        except Exception as exc:
            book.last_error = type(exc).__name__
            _log(f"response skipped ({type(exc).__name__})")
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

                def _handler(request, live=live_page, pre=prematch_page):
                    on_finished(request, live, pre)

                context.on("requestfinished", _handler)
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
                _write_status(book, force=True)
                _log("Watching get_main_line.erisgaming. Ctrl+C stops only this collector.")
                _log(f"tabs={len(context.pages)} live={book.live_page}")
                _log(f"prematch tab {book.prematch_page}")
                _log("The live tab stays in front until it sends a feed. Prematch is not reloaded on a timer.")
                last_heartbeat = time.time()
                watching_since = last_heartbeat
                last_prematch_open = time.time()
                blips = {"n": 0}
                quiet = {"focus": "live", "woke_live": False, "woke_prematch": False}
                while True:
                    republish()
                    try:
                        live_page.wait_for_timeout(5000)
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
                    now = time.time()
                    open_for = now - watching_since
                    if should_wake_silent_live(
                        live_requests=book.live_requests,
                        seconds_open=open_for,
                        on_sportsbook="sportsbook/live" in (book.live_page or "").lower(),
                        challenge=is_challenge_text("", book.live_page),
                        already_woke=quiet["woke_live"],
                    ):
                        quiet["woke_live"] = True
                        _log(
                            "No live feed since attach. The tab had already loaded. "
                            "Reloading it once so this collector sees the response."
                        )
                        try:
                            live_page.bring_to_front()
                        except Exception:
                            pass
                        _reload_once(live_page, "live")
                    if should_wake_silent_live(
                        live_requests=book.prematch_requests,
                        seconds_open=open_for,
                        on_sportsbook="sportsbook/prelive" in (book.prematch_page or "").lower(),
                        challenge=is_challenge_text("", book.prematch_page),
                        already_woke=quiet["woke_prematch"],
                        minimum_seconds=15,
                    ):
                        quiet["woke_prematch"] = True
                        _log(
                            "No prematch feed since attach. The tab had already loaded. "
                            "Reloading it once so this collector sees the response."
                        )
                        try:
                            prematch_page.bring_to_front()
                        except Exception:
                            pass
                        _reload_once(prematch_page, "prematch")
                    if now - last_heartbeat >= 30:
                        last_heartbeat = now
                        live_read = read_tab_quickly(live_page)
                        title = live_read[0] if live_read else ""
                        _log(
                            f"still watching api_seen={book.api_seen} "
                            f"get_main_line={book.snapshots_seen} "
                            f"last_api={book.last_api_path} title={title!r} "
                            f"live={book.live_page}"
                        )
                        live_silent = book.live_requests == 0
                        try:
                            if live_silent or quiet["focus"] == "live":
                                live_page.bring_to_front()
                                quiet["focus"] = "prematch" if not live_silent else "live"
                            else:
                                prematch_page.bring_to_front()
                                quiet["focus"] = "live"
                        except Exception:
                            pass
                        if live_read is None:
                            _log("Live tab title was not read. Leaving it open.")
                        elif is_challenge_text(title, live_read[1]):
                            _log("Cloudflare check is on the live tab. Waiting for it to finish.")
                        elif should_reload_live(title, book.live_page):
                            _log("Live tab left the sportsbook. Opening it again.")
                            _goto(live_page, live_page_url(), "live")
                        prematch_read = read_tab_quickly(prematch_page)
                        if prematch_read is None:
                            _log("Prematch tab title was not read. Leaving it open.")
                        elif is_challenge_text(prematch_read[0], prematch_read[1]):
                            _log("Cloudflare check is on the prematch tab. Waiting for it to finish.")
                        elif (
                            should_reload_prematch(prematch_read[0], book.prematch_page)
                            and now - last_prematch_open >= PREMATCH_REOPEN_SECONDS
                        ):
                            last_prematch_open = now
                            _log("Prematch tab left prelive. Opening it again.")
                            _goto(prematch_page, prematch_page_url(), "prematch")
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
