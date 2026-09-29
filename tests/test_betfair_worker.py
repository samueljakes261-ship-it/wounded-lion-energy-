"""Betfair worker health, snapshot, and 3-second poll tests. HTTP is mocked."""
import json
import time

from betfair.config import POLL_INTERVAL_SECONDS
from betfair.http import FetchResult
from betfair.worker import BetfairValuebetsWorker, Diagnostics, acquire_once


def _ok_result(body):
    return FetchResult(
        url="https://verigood.top/valuebets",
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=128,
        elapsed_seconds=0.05,
        json_body=body,
    )


def test_poll_interval_is_three_seconds():
    assert POLL_INTERVAL_SECONDS == 3
    worker = BetfairValuebetsWorker()
    assert worker._poll_interval_seconds == 3


def test_successful_empty_list_is_running_not_fake_data():
    worker = BetfairValuebetsWorker(poll_fn=lambda: ([], Diagnostics(endpoint_status="ok")))
    worker._run_one_cycle()
    status = worker.get_status()
    assert status["health"] == "RUNNING"
    assert status["event_count"] == 0
    assert worker.get_opportunities() == []


def test_invalid_json_is_not_a_healthy_cycle():
    worker = BetfairValuebetsWorker()

    def fail():
        return [], Diagnostics(
            endpoint_status="invalid_json",
            http_status_code=200,
            parser_error="invalid JSON: boom",
        )

    worker._poll_fn = fail
    worker._run_one_cycle()
    status = worker.get_status()
    assert status["health"] == "STARTING"
    assert status["error"]
    assert worker.get_opportunities() == []


def test_three_failures_degrade_health():
    worker = BetfairValuebetsWorker()
    calls = {"n": 0}

    def poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return [], Diagnostics(endpoint_status="ok")
        return [], Diagnostics(endpoint_status="http_error", parser_error="HTTP 401")

    worker._poll_fn = poll
    worker._run_one_cycle()
    assert worker.get_status()["health"] == "RUNNING"
    worker._run_one_cycle()
    worker._run_one_cycle()
    worker._run_one_cycle()
    assert worker.get_status()["health"] == "DEGRADED"


def test_latest_successful_snapshot_replaces_previous(tmp_path):
    cache = tmp_path / "cached_betfair_opportunities.json"
    from betfair.parser import parse_payload

    first = parse_payload(
        [
            {
                "cluster_id": "a",
                "match_cluster_id": "m",
                "home_team": "A",
                "away_team": "B",
                "start_time": "2026-10-01T18:45:00Z",
                "sport_key": "soccer",
                "league": "L",
                "market_label": "M",
                "direction": "LAY",
                "ref_bookmaker": "Betfair",
                "best_back_bookmaker": "Kolay91",
                "status": "MATCHED_NO_VALUE",
                "outcome": "draw",
                "is_live": False,
                "detected_at": "2026-09-29T20:48:01Z",
                "first_seen_at": "2026-09-29T20:41:56Z",
                "last_updated_at": "2026-09-29T20:41:56Z",
            }
        ]
    ).opportunities
    second = parse_payload(
        [
            {
                "cluster_id": "b",
                "match_cluster_id": "n",
                "home_team": "C",
                "away_team": "D",
                "start_time": "2026-10-01T18:45:00Z",
                "sport_key": "soccer",
                "league": "L",
                "market_label": "M",
                "direction": "BACK",
                "ref_bookmaker": "Betfair",
                "best_back_bookmaker": "Kolay91",
                "status": "VALUE",
                "outcome": "home",
                "is_live": True,
                "live_clock": "12:00",
                "detected_at": "2026-09-29T20:48:01Z",
                "first_seen_at": "2026-09-29T20:41:56Z",
                "last_updated_at": "2026-09-29T20:41:56Z",
            }
        ]
    ).opportunities

    calls = {"n": 0}

    def poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return first, Diagnostics(endpoint_status="ok", valid_count=1, prematch_count=1)
        return second, Diagnostics(endpoint_status="ok", valid_count=1, live_count=1)

    worker = BetfairValuebetsWorker(poll_fn=poll, cache_file=cache)
    worker._run_one_cycle()
    assert worker.get_opportunities()[0].home_team == "A"
    worker._run_one_cycle()
    remaining = worker.get_opportunities()
    assert len(remaining) == 1
    assert remaining[0].home_team == "C"
    assert remaining[0].is_live is True
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["opportunities"][0]["homeTeam"] == "C"


def test_failed_poll_does_not_clear_last_good_snapshot():
    from betfair.parser import parse_payload

    good = parse_payload(
        [
            {
                "cluster_id": "a",
                "match_cluster_id": "m",
                "home_team": "A",
                "away_team": "B",
                "start_time": "2026-10-01T18:45:00Z",
                "sport_key": "soccer",
                "league": "L",
                "market_label": "M",
                "direction": "LAY",
                "ref_bookmaker": "Betfair",
                "best_back_bookmaker": "Kolay91",
                "status": "MATCHED_NO_VALUE",
                "outcome": "draw",
                "is_live": False,
                "detected_at": "2026-09-29T20:48:01Z",
                "first_seen_at": "2026-09-29T20:41:56Z",
                "last_updated_at": "2026-09-29T20:41:56Z",
            }
        ]
    ).opportunities
    calls = {"n": 0}

    def poll():
        calls["n"] += 1
        if calls["n"] == 1:
            return good, Diagnostics(endpoint_status="ok")
        return [], Diagnostics(endpoint_status="http_error", parser_error="HTTP 500")

    worker = BetfairValuebetsWorker(poll_fn=poll)
    worker._run_one_cycle()
    worker._run_one_cycle()
    assert worker.get_opportunities()[0].home_team == "A"
    assert worker.get_status()["health"] in ("RUNNING", "DEGRADED")


def test_acquire_once_does_not_treat_http_200_token_error_as_success():
    result = acquire_once(
        fetch_fn=lambda *args, **kwargs: _ok_result({"detail": "Token gerekli"})
    )
    opportunities, diagnostics = result
    assert opportunities == []
    assert diagnostics.endpoint_status == "bad_payload"
    assert diagnostics.parser_error


def test_worker_loop_does_not_overlap_slow_polls():
    in_flight = {"n": 0, "max": 0}

    def poll():
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        time.sleep(0.05)
        in_flight["n"] -= 1
        return [], Diagnostics(endpoint_status="ok")

    worker = BetfairValuebetsWorker(poll_fn=poll, poll_interval_seconds=0.01)
    worker.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and worker.get_status()["poll_count"] < 2:
        time.sleep(0.02)
    worker.stop(timeout=1)
    assert in_flight["max"] == 1
    assert in_flight["n"] == 0
    assert worker.get_status()["poll_count"] >= 2
