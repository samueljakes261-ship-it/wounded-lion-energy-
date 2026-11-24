"""The Onwin VPS runner stays off Kolay90 and off production ingest."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from experiments.onwin_vps.book import CollectionBook
from experiments.onwin_vps.safety import OnwinVpsGuardError, validate_target

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


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
    assert "--headless=new" in chrome
    assert "TigerVNC" not in chrome
    assert "--no-sandbox" not in chrome
    assert "--disable-gpu" not in chrome
    assert "kolay90_direct/chrome_profile" not in chrome
    assert "chromium.launch" not in collector
    assert "launch_persistent_context" not in collector
    assert "connect_over_cdp" in collector
    local = (ROOT / "parsers" / "onwin" / "local_collector.py").read_text(encoding="utf-8")
    assert "ONWIN_VPS" not in local


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
    assert store_local_snapshot([], NOW)["accepted"] is False
    assert not (tmp_path / "live.json").exists()
    stored = store_local_snapshot([match], NOW)
    assert stored["accepted"] is True
    assert stored["count"] == 1
    feed = live_feed(NOW)
    assert feed["event_count"] == 1
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
