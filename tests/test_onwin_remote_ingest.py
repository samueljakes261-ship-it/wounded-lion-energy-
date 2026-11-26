"""OnWin live odds from the local Chrome enter the engine without ZenRows."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from models.match import MatchOdds
from parsers.onwin.local_collector import feed_kind, snapshot_lane, unwrap_sports
from parsers.onwin.parser import FOOTBALL_SPORT_ID
from parsers.onwin.prematch_snapshot import (
    accept_remote_snapshot as accept_prematch,
    load_fresh_matches as load_prematch,
    match_to_payload as prematch_payload,
    prefer_remote_onwin,
)
from parsers.onwin.remote_snapshot import (
    accept_remote_snapshot,
    live_feed,
    match_to_payload,
    snapshot_path,
)

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def _match():
    return MatchOdds(
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


@pytest.fixture
def snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / "onwin_remote_snapshot.json"
    monkeypatch.setenv("ONWIN_REMOTE_SNAPSHOT", str(path))
    monkeypatch.setenv("ONWIN_INGEST_TOKEN", "local-test-token")
    monkeypatch.setenv("MAX_ODDS_AGE_SECONDS", "30")
    return path


def test_feed_kind_matches_the_live_sportsbook_paths():
    snapshot = (
        "https://api-onwin-tr--prd--sb.4297.lol/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.get_main_line.erisgaming"
    )
    update = (
        "https://api-onwin-tr--prd--sb.4297.lol/frontserver-erisgaming__api/rpc/"
        "sumstats.frontserver.command.find_event_snapshots.erisgaming"
    )
    assert feed_kind(snapshot) == "snapshot"
    assert feed_kind(update) == "update"
    assert feed_kind(snapshot.replace("get_main_line.erisgaming", "get_main_line_schema")) is None
    compact = snapshot.replace("get_main_line.erisgaming", "get_main_line_compact.erisgaming")
    gap = snapshot.replace("get_main_line.erisgaming", "get_main_line_gap.erisgaming")
    assert feed_kind(compact) == "snapshot"
    assert feed_kind(gap) == "update"
    wrapped = unwrap_sports({"result": {"sports": {"football": {}}}})
    assert wrapped["sports"]["football"] == {}


def test_ingest_stores_live_rows_and_rejects_a_bad_token(snapshot_file):
    result = accept_remote_snapshot(
        {"matches": [match_to_payload(_match())]},
        "Bearer local-test-token",
        NOW,
    )
    assert result["accepted"] is True
    assert result["count"] == 1
    stored = json.loads(snapshot_path().read_text(encoding="utf-8"))
    assert stored["matches"][0]["bookmaker"] == "OnWin"
    assert stored["matches"][0]["feed_type"] == "live"
    assert "cookie" not in json.dumps(stored)
    with pytest.raises(Exception) as rejected:
        accept_remote_snapshot(
            {"matches": [match_to_payload(_match())]},
            "Bearer wrong",
            NOW,
        )
    assert rejected.value.status_code == 401


def test_pc_clock_skew_is_stored_at_vps_receipt_time(snapshot_file):
    row = match_to_payload(_match())
    row["feed_type"] = "prematch"
    with pytest.raises(Exception) as rejected:
        accept_remote_snapshot({"matches": [row]}, "Bearer local-test-token", NOW)
    assert rejected.value.status_code == 400
    skewed = match_to_payload(_match())
    skewed["collected_at"] = (NOW - timedelta(minutes=5)).isoformat()
    result = accept_remote_snapshot(
        {"matches": [skewed]},
        "Bearer local-test-token",
        NOW,
    )
    assert result["accepted"] is True
    assert result["collected_at"] == NOW.isoformat()
    assert live_feed(NOW)["matches"][0].home_team == "Home"
    assert live_feed(NOW + timedelta(seconds=31)) is None


def test_live_feed_is_fresh_only_inside_the_engine_window(snapshot_file):
    accept_remote_snapshot(
        {"matches": [match_to_payload(_match())]},
        "Bearer local-test-token",
        NOW,
    )
    feed = live_feed(NOW)
    assert feed["event_count"] == 1
    assert feed["age"] == 0
    assert feed["matches"][0].bookmaker == "OnWin"
    assert feed["matches"][0].feed_type == "live"
    assert live_feed(NOW + timedelta(seconds=31)) is None


def _tree(status: str) -> dict:
    return {
        "sports": {
            FOOTBALL_SPORT_ID: {
                "categories": {
                    "c": {
                        "tournaments": {
                            "t": {"events": {"e": {"diff": {"status": status}}}}
                        }
                    }
                }
            }
        }
    }


def test_snapshot_lane_separates_live_and_prematch():
    assert snapshot_lane(_tree("in_progress")) == "live"
    assert snapshot_lane(_tree("not_started")) == "prematch"
    mixed = _tree("in_progress")
    mixed["sports"][FOOTBALL_SPORT_ID]["categories"]["c"]["tournaments"]["t2"] = {
        "events": {"e2": {"diff": {"status": "not_started"}}}
    }
    assert snapshot_lane(mixed) is None


def test_prematch_ingest_uses_the_same_token_and_stays_out_of_live(snapshot_file, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ONWIN_PREMATCH_REMOTE_SNAPSHOT",
        str(tmp_path / "onwin_prematch.json"),
    )
    row = prematch_payload(_match())
    row["feed_type"] = "prematch"
    row["collected_at"] = (NOW - timedelta(minutes=5)).isoformat()
    result = accept_prematch({"matches": [row]}, "Bearer local-test-token", NOW)
    assert result["accepted"] is True
    assert result["collected_at"] == NOW.isoformat()
    stored = load_prematch(NOW)
    assert stored[0].feed_type == "prematch"
    assert stored[0].home_team == "Home"
    assert prefer_remote_onwin([_match()], NOW)[0].feed_type == "prematch"
    assert load_prematch(NOW + timedelta(seconds=901)) is None
    with pytest.raises(Exception) as rejected:
        accept_prematch({"matches": [match_to_payload(_match())]}, "Bearer local-test-token", NOW)
    assert rejected.value.status_code == 400
