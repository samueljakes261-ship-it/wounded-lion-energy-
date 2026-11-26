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
import time
import urllib.request
from pathlib import Path

from experiments.onwin_vps.book import CollectionBook
from experiments.onwin_vps.safety import OnwinVpsGuardError, validate_target
from parsers.onwin.local_collector import (
    _open_tabs,
    _owner_page,
    feed_kind,
    PREMATCH_REOPEN_SECONDS,
    should_reload_live,
    should_reload_prematch,
    snapshot_lane,
    unwrap_sports,
)
from parsers.onwin.prematch_snapshot import store_local_snapshot as store_prematch
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


def _write_status(book: CollectionBook) -> None:
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


def needs_chrome_restart(error_name: str, listening: bool) -> bool:
    """Restart Chrome only when its debugging port is down.

    TimeoutError and a closed tab, while port 9223 is still open, are a
    dropped Playwright session. Attach again. Killing Chrome ended the
    session that was already storing live odds.
    """
    del error_name
    return not listening


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


def _close_created(playwright, created) -> None:
    for page in created or []:
        try:
            page.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass


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

    Reloading a prelive tab that was still loading aborted get_main_line.
    The listener is already attached, so the next response is captured
    without starting the navigation again.
    """
    current = (page.url or "").lower()
    marker = "sportsbook/prelive" if label == "prematch" else "sportsbook/live"
    if marker in current:
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

    def publish_live(force: bool = False, from_network: bool = True) -> None:
        if not state.initialized:
            return
        matches = state.get_match_odds()
        if not matches:
            return
        now = time.time()
        if force:
            if now - live_post["last"] < 10:
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
        _write_status(book)

    def publish_prematch(force: bool = False, from_network: bool = True) -> None:
        matches = prematch["matches"]
        if not matches:
            return
        now = time.time()
        if force:
            if now - prematch["last_post"] < 60:
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
        _write_status(book)

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
            lane = ""
            if owner is prematch_page:
                lane = "prematch"
            elif owner is live_page:
                lane = "live"
            response = request.response()
            if response is None or response.status >= 400:
                book.note_traffic(kind, lane)
                _write_status(book)
                return
            payload = unwrap_sports(json.loads(response.body()))
            if payload is None:
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
                    _write_status(book)
                    return
                prematch["matches"] = matches
                publish_prematch(from_network=True)
                return
            if lane != "live":
                _write_status(book)
                return
            if kind == "snapshot":
                state.load_initial(payload)
                saw_live["ok"] = True
                odds = state.get_match_odds()
                _log(f"get_main_line events={state.event_count} odds={len(odds)}")
                if odds:
                    publish_live(from_network=True)
                else:
                    _write_status(book)
                return
            if saw_live["ok"]:
                changed = state.apply_update(payload)
                odds = state.get_match_odds()
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
    try:
        while True:
            playwright = None
            created: list = []
            failed = False
            try:
                book.chrome_listening = _chrome_listening()
                _write_status(book)
                if not book.chrome_listening:
                    raise RuntimeError("cdp down")
                _log(f"Attaching to dedicated Chrome at {cdp_url()}")
                playwright = sync_playwright().start()
                browser = playwright.chromium.connect_over_cdp(cdp_url(), timeout=45000)
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
                _refresh(live_page, live_page_url(), "live")
                book.live_page = live_page.url or ""
                _write_status(book)
                _refresh(prematch_page, prematch_page_url(), "prematch")
                book.live_page = live_page.url or ""
                book.prematch_page = prematch_page.url or ""
                book.page_loaded = _pages_loaded(book.live_page, book.prematch_page)
                book.phase = "watching"
                _write_status(book)
                _log("Watching get_main_line.erisgaming. Ctrl+C stops only this collector.")
                _log(f"live tab {book.live_page}")
                _log(f"prematch tab {book.prematch_page}")
                _log("Prematch stays on the open prelive tab. It is not reloaded on a timer.")
                last_heartbeat = time.time()
                last_prematch_open = time.time()
                while True:
                    live_page.wait_for_timeout(5000)
                    try:
                        book.live_page = live_page.url or ""
                        book.prematch_page = prematch_page.url or ""
                        book.page_loaded = _pages_loaded(book.live_page, book.prematch_page)
                        book.chrome_listening = True
                        book.attached = True
                    except Exception as exc:
                        book.last_error = type(exc).__name__
                        raise
                    publish_live(force=True, from_network=False)
                    publish_prematch(force=True, from_network=False)
                    now = time.time()
                    if now - last_heartbeat >= 30:
                        last_heartbeat = now
                        title = ""
                        try:
                            title = live_page.title()
                        except Exception:
                            title = ""
                        _log(
                            f"still watching api_seen={book.api_seen} "
                            f"get_main_line={book.snapshots_seen} "
                            f"last_api={book.last_api_path} title={title!r} "
                            f"live={book.live_page}"
                        )
                        if "just a moment" in title.lower() or "cloudflare" in title.lower():
                            _log("Cloudflare check is on the live tab. Waiting for it to finish.")
                        elif should_reload_live(title, book.live_page):
                            _log("Live tab left the sportsbook. Opening it again.")
                            _goto(live_page, live_page_url(), "live")
                        prematch_title = ""
                        try:
                            prematch_title = prematch_page.title()
                        except Exception:
                            prematch_title = ""
                        if "just a moment" in prematch_title.lower() or "cloudflare" in prematch_title.lower():
                            _log("Cloudflare check is on the prematch tab. Waiting for it to finish.")
                        elif (
                            should_reload_prematch(prematch_title, book.prematch_page)
                            and now - last_prematch_open >= PREMATCH_REOPEN_SECONDS
                        ):
                            last_prematch_open = now
                            _log("Prematch tab left prelive. Opening it again.")
                            _goto(prematch_page, prematch_page_url(), "prematch")
                    _write_status(book)
            except KeyboardInterrupt:
                _log("Stopped. The dedicated Chrome stays open.")
                _close_created(playwright, created)
                return 0
            except Exception as exc:
                failed = True
                book.attached = False
                book.chrome_listening = _chrome_listening()
                book.recovery_attempts += 1
                book.last_error = type(exc).__name__
                _write_status(book)
                _log(f"Chrome attach failed ({type(exc).__name__}).")
            finally:
                if failed:
                    _close_created(playwright, created)
            if not failed:
                continue
            delay = 15
            restart = needs_chrome_restart(book.last_error or "", book.chrome_listening)
            if not restart:
                _log("Chrome is still listening on port 9223. Attaching again.")
            elif time.time() - last_chrome_restart > 180:
                last_chrome_restart = time.time()
                _log("Chrome's debugging port is down. Restarting the Onwin Chrome only.")
                try:
                    completed = subprocess.run(
                        [str(CHROME_SCRIPT), "restart"],
                        cwd=str(ROOT),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=75,
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
                delay = 180
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
