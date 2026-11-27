"""The Onwin VPS runner stays off Kolay90 and off production ingest."""

import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from experiments.onwin_vps.book import CollectionBook
from experiments.onwin_vps.safety import OnwinVpsGuardError, validate_target
from parsers.onwin.parser import FOOTBALL_SPORT_ID

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def _live_tree(home: str = "LiveHome") -> dict:
    return {
        "sports": {
            FOOTBALL_SPORT_ID: {
                "categories": {
                    "c": {
                        "tournaments": {
                            "t": {
                                "events": {
                                    "e": {
                                        "diff": {
                                            "status": "in_progress",
                                            "startTime": 1787400000000,
                                            "participants": {
                                                "team1": {"name": home, "teamId": "h"},
                                                "team2": {"name": "Away", "teamId": "a"},
                                            },
                                        },
                                        "scopes": {
                                            "normal_time--0": {
                                                "markets": {
                                                    "score_1x2--nil": {
                                                        "outcomes": {
                                                            "outcome::p1": {"coefficient": 2.1, "updatedAt": 1},
                                                            "outcome::draw": {"coefficient": 3.2, "updatedAt": 1},
                                                            "outcome::p2": {"coefficient": 3.4, "updatedAt": 1},
                                                        }
                                                    }
                                                }
                                            }
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }


def test_onwin_chrome_refuses_the_kolay_port_and_profile(tmp_path):
    with pytest.raises(OnwinVpsGuardError):
        validate_target(9222, tmp_path / "onwin")
    with pytest.raises(OnwinVpsGuardError):
        validate_target(9223, tmp_path / "kolay90_direct" / "chrome_profile")
    validate_target(9223, tmp_path / "experiments" / "onwin_vps" / "chrome_profile")


def test_success_requires_odds_and_a_successful_post():
    book = CollectionBook()
    assert book.note_odds("live", 0, publish_ok=None, now=NOW) is False
    assert book.last_live_success is None
    assert book.note_odds("live", 12, events=40, markets=1, publish_ok=False, now=NOW) is False
    assert book.last_live_success is None
    assert book.live_odds == 0
    assert book.note_odds("live", 12, events=40, markets=1, publish_ok=None, now=NOW) is True
    assert book.live_odds == 12
    assert book.live_events == 40
    assert book.live_markets == 1
    assert book.last_live_success == NOW.isoformat()
    assert book.session_valid is True
    later = datetime(2026, 11, 24, 12, 5, tzinfo=timezone.utc)
    assert book.note_odds("live", 0, publish_ok=None, now=later) is False
    assert book.last_live_success == NOW.isoformat()
    assert book.live_odds == 12
    assert book.note_odds(
        "live", 12, publish_ok=None, from_network=False, now=later
    ) is False
    assert book.last_live_success == NOW.isoformat()
    book.last_error = "TimeoutError: attach"
    assert book.note_odds(
        "prematch", 4, events=4, markets=1, publish_ok=True, from_network=False, now=later
    ) is True
    assert book.last_error == "TimeoutError: attach"
    assert book.prematch_odds == 4
    assert book.note_odds("prematch", 4, events=4, markets=2, publish_ok=True, now=NOW) is True
    assert book.prematch_odds == 4
    assert book.prematch_markets == 2
    status = book.status(publish=False, cdp_url="http://127.0.0.1:9223", profile="/tmp/onwin")
    assert status["playwright_browser_launched"] is False
    assert status["publish_to_engine"] is False
    assert status["zenrows_used"] is False
    assert status["get_main_line_seen"] == 0


def test_vps_runner_does_not_launch_a_browser_or_touch_kolay():
    chrome = (ROOT / "experiments" / "onwin_vps" / "chrome.sh").read_text(encoding="utf-8")
    collector = (ROOT / "experiments" / "onwin_vps" / "collector.py").read_text(encoding="utf-8")
    assert "9223" in chrome
    assert "--remote-debugging-address=127.0.0.1" in chrome
    assert "Xvfb" in chrome
    assert ":98" in chrome
    assert "--headless=new" not in chrome
    assert "display :1 belongs to Kolay90" in chrome
    assert "/snap/bin/chromium" in chrome
    assert "chrome.sh install" in chrome
    assert "TigerVNC" not in chrome
    assert "retrying without the Chrome sandbox" in chrome
    assert 'args+=("$LIVE_PAGE" "$PREMATCH_PAGE")' in chrome
    assert "9>&-" in chrome
    assert "lock_holders" in chrome
    assert "ps -eo pid=,args=" not in chrome
    assert "already on the sportsbook" in collector
    assert "/proc/net/tcp" in chrome
    assert "debugger_ready" in chrome
    assert "disable-background-timer-throttling" in chrome
    assert "page.close" not in collector
    assert "--disable-gpu" not in chrome
    assert "kolay90_direct/chrome_profile" not in chrome
    assert "chromium.launch" not in collector
    assert "launch_persistent_context" not in collector
    assert "connect_over_cdp" in collector
    assert "threading.Thread" not in collector
    local = (ROOT / "parsers" / "onwin" / "local_collector.py").read_text(encoding="utf-8")
    assert "ONWIN_VPS" not in local


def test_a_dropped_debugger_reattaches_while_chrome_stays_up():
    from experiments.onwin_vps.collector import chrome_log_excerpt, needs_chrome_restart, should_reload_live
    from parsers.onwin.local_collector import health_url, should_reload_prematch

    assert needs_chrome_restart("TimeoutError", True) is False
    assert needs_chrome_restart(
        "TimeoutError: BrowserType.connect_over_cdp: Timeout 20000ms exceeded.",
        True,
        1,
    ) is True
    assert needs_chrome_restart("TargetClosedError", True) is False
    assert needs_chrome_restart("Error", True) is False
    assert needs_chrome_restart("Error", True, 3) is False
    assert needs_chrome_restart("Error", True, 4) is True
    assert needs_chrome_restart("Error", False) is True
    assert needs_chrome_restart("TimeoutError", False) is True
    sportsbook = "https://onwin4920.com/sportsbook/live/main-line/soccer"
    assert should_reload_live("Just a moment...", sportsbook) is False
    assert should_reload_live("Onwin Bahis ve Casino Sitesi", sportsbook) is False
    assert should_reload_live("Onwin", "https://onwin4920.com/") is True
    prelive = "https://onwin4920.com/sportsbook/prelive/main-line/soccer"
    assert should_reload_prematch("Just a moment...", prelive) is False
    assert should_reload_prematch("Onwin Bahis ve Casino Sitesi", prelive) is False
    assert should_reload_prematch("Onwin", "https://onwin4920.com/") is True
    assert should_reload_prematch("", "about:blank") is False
    assert should_reload_prematch(
        "",
        "https://onwin4920.com/cdn-cgi/challenge-platform/h/b/orchestrate",
    ) is False
    from experiments.onwin_vps.collector import should_refresh_quiet_tab

    assert should_refresh_quiet_tab(
        challenge=True,
        on_sportsbook=True,
        seconds_since_response=1000,
        seconds_since_refresh=1000,
    ) is False
    assert should_refresh_quiet_tab(
        challenge=False,
        on_sportsbook=True,
        seconds_since_response=30,
        seconds_since_refresh=1000,
    ) is False
    assert should_refresh_quiet_tab(
        challenge=False,
        on_sportsbook=True,
        seconds_since_response=1000,
        seconds_since_refresh=1000,
    ) is False
    from experiments.onwin_vps.collector import (
        LIVE_HOLD_SECONDS,
        PREMATCH_HOLD_SECONDS,
        adopt_live_book,
        should_republish,
    )
    from parsers.onwin.state import OnwinState

    from experiments.onwin_vps.collector import (
        live_page_is_challenge,
        should_load_live_page,
        should_open_live_page,
        should_wake_silent_live,
    )
    from parsers.onwin.local_collector import page_lane

    assert page_lane(type("P", (), {"url": "https://onwin4921.com/sportsbook/live/main-line/soccer"})(), None, None) == "live"
    assert page_lane(type("P", (), {"url": "https://onwin4921.com/sportsbook/prelive/main-line/soccer"})(), None, None) == "prematch"
    assert should_wake_silent_live(
        live_requests=0, seconds_open=50, on_sportsbook=True, challenge=False, already_woke=False
    ) is True
    assert should_wake_silent_live(
        live_requests=0, seconds_open=5, on_sportsbook=True, challenge=False, already_woke=False
    ) is False
    assert should_wake_silent_live(
        live_requests=0,
        seconds_open=20,
        on_sportsbook=True,
        challenge=False,
        already_woke=False,
        minimum_seconds=15,
    ) is True
    assert should_wake_silent_live(
        live_requests=1, seconds_open=50, on_sportsbook=True, challenge=False, already_woke=False
    ) is False
    assert should_wake_silent_live(
        live_requests=0, seconds_open=50, on_sportsbook=True, challenge=True, already_woke=False
    ) is False
    assert should_wake_silent_live(
        live_requests=0, seconds_open=50, on_sportsbook=True, challenge=False, already_woke=True
    ) is False
    assert should_wake_silent_live(
        live_requests=0,
        seconds_open=34,
        on_sportsbook=True,
        challenge=False,
        already_woke=False,
        wakes=1,
        max_wakes=4,
        gap_seconds=25,
    ) is True
    assert should_wake_silent_live(
        live_requests=0,
        seconds_open=20,
        on_sportsbook=True,
        challenge=False,
        already_woke=False,
        wakes=1,
        max_wakes=4,
        gap_seconds=25,
    ) is False
    assert should_wake_silent_live(
        live_requests=0,
        seconds_open=200,
        on_sportsbook=True,
        challenge=False,
        already_woke=False,
        wakes=4,
        max_wakes=4,
        gap_seconds=25,
    ) is False
    from parsers.onwin.local_collector import resolve_lane

    assert should_load_live_page(
        live_requests=0, seconds_since_traffic=8, challenge=False, loads=0, quiet_reloads=0,
        saw_challenge=False, seconds_since_clear=8,
    ) is False
    assert should_load_live_page(
        live_requests=0, seconds_since_traffic=60, challenge=True, loads=0, quiet_reloads=0,
        saw_challenge=True, seconds_since_clear=0,
    ) is False
    assert should_load_live_page(
        live_requests=4, seconds_since_traffic=75, challenge=False, loads=1, quiet_reloads=0,
        saw_challenge=False, seconds_since_clear=75,
    ) is False
    assert should_load_live_page(
        live_requests=4, seconds_since_traffic=30, challenge=False, loads=1, quiet_reloads=0,
        saw_challenge=False, seconds_since_clear=30,
    ) is False
    assert live_page_is_challenge("Just a moment...", "https://onwin4921.com/sportsbook/live/main-line/soccer", "") is True
    assert live_page_is_challenge("Onwin", "https://onwin4921.com/sportsbook/live/main-line/soccer", "Checking your browser") is True
    assert live_page_is_challenge("Onwin", "https://onwin4921.com/sportsbook/live/main-line/soccer", "Main line") is False
    assert should_open_live_page(
        live_requests=0, seconds_open=5, challenge=False, opened=False, readable=True,
        saw_challenge=False, seconds_since_clear=5,
    ) is False
    assert should_open_live_page(
        live_requests=0, seconds_open=30, challenge=True, opened=False, readable=True,
        saw_challenge=True, seconds_since_clear=0,
    ) is False
    assert should_open_live_page(
        live_requests=0, seconds_open=40, challenge=False, opened=False, readable=True,
        saw_challenge=True, seconds_since_clear=10,
    ) is False
    assert should_open_live_page(
        live_requests=0, seconds_open=60, challenge=False, opened=False, readable=True,
        saw_challenge=True, seconds_since_clear=25,
    ) is False
    assert should_open_live_page(
        live_requests=0, seconds_open=60, challenge=False, opened=True, readable=True,
        saw_challenge=False, seconds_since_clear=60,
    ) is False
    assert resolve_lane("", "snapshot", _live_tree()) == "live"
    assert resolve_lane("prematch", "snapshot", _live_tree()) == "prematch"
    assert resolve_lane("", "update", None) == "live"
    assert should_republish(seconds_since_network=10, hold_seconds=LIVE_HOLD_SECONDS) is True
    assert should_republish(seconds_since_network=LIVE_HOLD_SECONDS, hold_seconds=LIVE_HOLD_SECONDS) is True
    assert should_republish(seconds_since_network=LIVE_HOLD_SECONDS + 1, hold_seconds=LIVE_HOLD_SECONDS) is False
    assert should_republish(seconds_since_network=800, hold_seconds=PREMATCH_HOLD_SECONDS) is True
    assert should_republish(seconds_since_network=-1, hold_seconds=LIVE_HOLD_SECONDS) is False
    state = OnwinState()
    state.load_initial(_live_tree())
    assert len(state.get_match_odds()) == 1
    assert adopt_live_book(state, {"sports": {}}) is False
    assert state.get_match_odds()[0].home_team == "LiveHome"
    assert adopt_live_book(state, _live_tree("OtherHome")) is True
    assert state.get_match_odds()[0].home_team == "OtherHome"
    assert health_url("https://api.example/onwin/live") == "https://api.example/health"
    excerpt = chrome_log_excerpt(
        [
            "[1124/160424.101564:ERROR:crashpad/util/process/process_memory.cc:43] short read",
            "ptrace: No such process (3)",
            "DevTools listening on 127.0.0.1:9223",
        ]
    )
    assert excerpt == "DevTools listening on 127.0.0.1:9223"


def test_a_failed_post_does_not_call_the_vps_down(monkeypatch, capsys):
    import requests

    from models.match import MatchOdds
    from parsers.onwin.local_collector import transmit
    from parsers.onwin.remote_snapshot import match_to_payload

    def post(url, json, headers, timeout):
        raise requests.ConnectionError("timed out")

    monkeypatch.setenv("ONWIN_INGEST_TOKEN", "local-test-token")
    monkeypatch.setattr("parsers.onwin.local_collector.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(requests, "post", post)
    match = MatchOdds(
        bookmaker="OnWin",
        competition="League",
        sport="football",
        market="1X2",
        home_team="Home",
        away_team="Away",
        home_odds=2.1,
        draw_odds=3.2,
        away_odds=3.4,
        start_time=NOW,
        collected_at=NOW,
        feed_type="live",
    )
    assert transmit(
        [match],
        "https://api.example/onwin/live",
        "live",
        match_to_payload,
        vps_up=True,
    ) is False
    logged = capsys.readouterr().out
    assert "VPS unavailable" not in logged
    assert "VPS is up" in logged
    assert "ConnectionError" in logged


def test_publish_defaults_to_the_local_snapshot(monkeypatch):
    monkeypatch.delenv("ONWIN_VPS_PUBLISH", raising=False)
    monkeypatch.delenv("ONWIN_VPS_CDP_URL", raising=False)
    monkeypatch.setenv("ONWIN_VPS_CDP_PORT", "9222")
    from experiments.onwin_vps import collector

    assert collector.publish_enabled() is True
    with pytest.raises(OnwinVpsGuardError):
        collector._guard()


def test_local_snapshot_needs_no_ingest_token(tmp_path, monkeypatch):
    from models.match import MatchOdds
    from parsers.onwin.prematch_snapshot import store_local_snapshot as store_prematch
    from parsers.onwin.remote_snapshot import live_feed, store_local_snapshot

    monkeypatch.delenv("ONWIN_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("ONWIN_REMOTE_SNAPSHOT", str(tmp_path / "live.json"))
    monkeypatch.setenv("ONWIN_PREMATCH_REMOTE_SNAPSHOT", str(tmp_path / "pre.json"))
    monkeypatch.setenv("MAX_ODDS_AGE_SECONDS", "30")
    match = MatchOdds(
        bookmaker="OnWin",
        competition="League",
        sport="football",
        market="1X2",
        home_team="Home",
        away_team="Away",
        home_odds=2.1,
        draw_odds=3.2,
        away_odds=3.4,
        start_time=NOW,
        collected_at=NOW,
        feed_type="live",
    )
    from parsers.onwin.remote_snapshot import peek_stored

    assert store_local_snapshot([], NOW)["accepted"] is False
    assert not (tmp_path / "live.json").exists()
    stored = store_local_snapshot([match], NOW)
    assert stored["accepted"] is True
    assert stored["count"] == 1
    feed = live_feed(NOW)
    assert feed["event_count"] == 1
    peeked = peek_stored(NOW + timedelta(seconds=31))
    assert peeked["age"] == 31
    assert peeked["matches"][0].home_team == "Home"
    empty = store_local_snapshot([], NOW + timedelta(seconds=5))
    assert empty["accepted"] is False
    assert live_feed(NOW)["event_count"] == 1
    prematch = MatchOdds(
        bookmaker="OnWin",
        competition="League",
        sport="football",
        market="1X2",
        home_team="Home",
        away_team="Away",
        home_odds=1.9,
        draw_odds=3.4,
        away_odds=4.0,
        start_time=NOW,
        collected_at=NOW,
        feed_type="prematch",
    )
    assert store_prematch([prematch], NOW)["accepted"] is True


def test_status_file_round_trip(tmp_path, monkeypatch):
    from experiments.onwin_vps import collector

    monkeypatch.setattr(collector, "OUTPUT", tmp_path)
    book = CollectionBook()
    book.note_odds("prematch", 3, publish_ok=None, now=NOW)
    collector._write_status(book)
    payload = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert payload["prematch_odds"] == 3
    assert payload["last_live_success"] is None
    assert payload["cdp_url"].endswith(":9223")


def test_reclaim_releases_a_lock_leaked_to_a_child():
    script = ROOT / "experiments" / "onwin_vps" / "chrome.sh"
    lock = ROOT / "experiments" / "onwin_vps" / "output" / "chrome.start.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        ["bash", "-c", 'exec 9>"$1"; flock -n 9; sleep 30', "bash", str(lock)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 5
        held = False
        while time.time() < deadline:
            probe = subprocess.run(
                ["bash", "-c", 'exec 9>"$1"; flock -n 9', "bash", str(lock)],
                check=False,
            )
            if probe.returncode != 0:
                held = True
                break
            time.sleep(0.05)
        assert held
        completed = subprocess.run(
            [str(script), "reclaim-lock"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stderr
        assert str(holder.pid) in completed.stderr
        released = subprocess.run(
            ["bash", "-c", 'exec 9>"$1"; flock -n 9', "bash", str(lock)],
            check=False,
        )
        assert released.returncode == 0
    finally:
        holder.kill()
        holder.wait(timeout=5)
