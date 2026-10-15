"""API exposure of Betfair opportunities and health. No live HTTP."""
import json
from datetime import datetime, timezone

import api
import collector
from betfair.models import LIVE, PREMATCH, UNKNOWN, BetfairOpportunity
from betfair.serialize import serialize_snapshot


def _opp(*, home, is_live, cluster):
    return BetfairOpportunity(
        cluster_id=cluster,
        match_cluster_id=cluster,
        home_team=home,
        away_team="Away",
        start_time=datetime(2026, 10, 1, 18, 45, tzinfo=timezone.utc),
        sport="soccer",
        league="League",
        market_label="Market",
        direction="LAY",
        ref_bookmaker="Betfair",
        best_back_bookmaker="Kolay91",
        status="MATCHED_NO_VALUE",
        outcome="draw",
        is_live=is_live,
        live_classification=LIVE if is_live is True else PREMATCH if is_live is False else UNKNOWN,
        detected_at=datetime(2026, 9, 29, 20, 48, tzinfo=timezone.utc),
        first_seen_at=datetime(2026, 9, 29, 20, 41, tzinfo=timezone.utc),
        last_updated_at=datetime(2026, 9, 29, 20, 41, tzinfo=timezone.utc),
    )


def test_opportunities_live_appends_only_live_betfair(monkeypatch, tmp_path):
    cache = tmp_path / "cached_betfair_opportunities.json"
    snapshot = serialize_snapshot(
        [
            _opp(home="Live", is_live=True, cluster="live"),
            _opp(home="Prematch", is_live=False, cluster="pre"),
            _opp(home="Unknown", is_live=None, cluster="unk"),
        ],
        last_success_at=1e12,
    )
    cache.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(collector, "BETFAIR_CACHE_FILE", cache)
    monkeypatch.setattr(api, "get_cached_opportunities", lambda: [{"feed": "turkish-live"}])
    monkeypatch.setattr(
        api, "get_cached_betfair_opportunities", collector.get_cached_betfair_opportunities
    )

    result = api.opportunities(mode="live")
    homes = [row.get("homeTeam") or row.get("feed") for row in result]
    assert "turkish-live" in homes
    assert "Live" in homes
    assert "Prematch" not in homes
    assert "Unknown" not in homes
    betfair = [row for row in result if row.get("opportunityType") == "BETFAIR"]
    assert all(row["source"] == "betfair" for row in betfair)
    assert all(row["isLive"] is True for row in betfair)


def test_opportunities_prematch_appends_only_prematch_betfair(monkeypatch, tmp_path):
    cache = tmp_path / "cached_betfair_opportunities.json"
    snapshot = serialize_snapshot(
        [
            _opp(home="Live", is_live=True, cluster="live"),
            _opp(home="Prematch", is_live=False, cluster="pre"),
        ],
        last_success_at=1e12,
    )
    cache.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(collector, "BETFAIR_CACHE_FILE", cache)
    monkeypatch.setattr(api, "get_cached_prematch_opportunities", lambda: [{"feed": "turkish-pre"}])
    monkeypatch.setattr(
        api, "get_cached_betfair_opportunities", collector.get_cached_betfair_opportunities
    )

    result = api.opportunities(mode="prematch")
    homes = [row.get("homeTeam") or row.get("feed") for row in result]
    assert "turkish-pre" in homes
    assert "Prematch" in homes
    assert "Live" not in homes


def test_status_includes_betfair_collector(monkeypatch, tmp_path):
    status_file = tmp_path / "cached_status.json"
    monkeypatch.setattr(collector, "STATUS_FILE", status_file)
    payload = collector.get_collector_status()
    assert "betfair" in payload["collectors"]
    assert payload["collectors"]["betfair"]["name"] == "Betfair"
    assert payload["collectors"]["betfair"]["collectorStatus"] == "STOPPED"


def test_start_prematch_and_live_workers_do_not_start_betfair():
    import inspect

    assert "betfair" not in inspect.getsource(collector.start_prematch_workers).lower()
    assert "betfair" not in inspect.getsource(collector.start_workers).lower()
    assert "start_betfair_worker" in inspect.getsource(__import__("run_engine"))
