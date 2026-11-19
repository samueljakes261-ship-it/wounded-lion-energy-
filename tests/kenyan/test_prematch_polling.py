"""PREMATCH poll cadence, freshness timestamps, and API snapshot updates."""
import time
from datetime import datetime, timedelta, timezone

from kenyan.config import (
    BETIKA,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    PREMATCH,
    SPORTPESA,
)
from kenyan.engine import KenyanArbitrageEngine
from kenyan.models import KenyanMatchOdds
from kenyan.runner import KenyanEngineRunner
from kenyan.workers import bet22, betika, onexbet, sportpesa
from kenyan.workers.base import BaseKenyanWorker, Diagnostics


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _match(bookmaker, home_odds, draw_odds, away_odds, *, event_id, collected_at=None):
    collected = collected_at or NOW
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="League",
        sport="Football",
        market="1X2",
        home_team="Alpha",
        away_team="Beta",
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=collected,
        confirmed_at=collected,
        event_id=event_id,
        status="PREMATCH",
    )


def _ok(**overrides):
    fields = dict(
        endpoint_status="ok",
        http_status_code=200,
        events_discovered=1,
        valid_normalized_events=1,
        acquired_at=time.time(),
    )
    fields.update(overrides)
    return Diagnostics(**fields)


def _pair(home_odds=2.10, collected_at=None):
    return [
        _match(SPORTPESA, home_odds, 3.30, 3.40, event_id="sp", collected_at=collected_at),
        _match(BETIKA, 2.00, 3.90, 4.00, event_id="bk", collected_at=collected_at),
    ]


def test_prematch_workers_are_scheduled_every_90_seconds():
    assert KENYAN_PREMATCH_POLL_INTERVAL_SECONDS == 90
    workers = (
        sportpesa.build_prematch_worker(),
        betika.build_prematch_worker(),
        onexbet.build_prematch_worker(),
        bet22.build_prematch_worker(),
    )
    assert {worker._poll_interval_seconds for worker in workers} == {90}


def test_repeated_polls_replace_the_snapshot_on_the_configured_interval():
    calls = []
    prices = iter([2.10, 2.40, 2.70])

    def poll_fn():
        calls.append(time.monotonic())
        price = next(prices)
        return (
            [_match(SPORTPESA, price, 3.30, 3.40, event_id="sp")],
            _ok(),
        )

    worker = BaseKenyanWorker("SportPesa_prematch", poll_fn, poll_interval_seconds=0.08)
    worker.start()
    try:
        deadline = time.monotonic() + 1.2
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker.stop()

    assert len(calls) >= 3
    gaps = [calls[index + 1] - calls[index] for index in range(2)]
    assert all(0.05 <= gap <= 0.2 for gap in gaps)
    assert worker.get_matches()[0].home_odds == 2.70
    status = worker.get_status()
    assert status["poll_status"] == "fresh"
    assert status["poll_interval_seconds"] == 0.08
    assert status["last_response_status"] == 200
    assert status["odds_parsed"] == 1
    assert status["last_successful_poll_at"] is not None
    assert status["freshness_age_seconds"] < 1


def test_failed_poll_does_not_stop_the_next_poll_or_refresh_timestamps():
    state = {"n": 0}

    def poll_fn():
        state["n"] += 1
        if state["n"] == 1:
            return [_match(SPORTPESA, 2.10, 3.30, 3.40, event_id="sp")], _ok()
        if state["n"] == 2:
            return [], Diagnostics(
                endpoint_status="http_error",
                http_status_code=503,
                parser_error="HTTP 503",
            )
        return [_match(SPORTPESA, 2.50, 3.10, 3.20, event_id="sp")], _ok()

    worker = BaseKenyanWorker("SportPesa_prematch", poll_fn, poll_interval_seconds=0.05)
    worker.start()
    try:
        deadline = time.monotonic() + 1.2
        while state["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker.stop()

    assert state["n"] >= 3
    assert worker.get_matches()[0].home_odds == 2.50
    assert worker.get_status()["last_poll_error"] is None


def test_a_failed_poll_keeps_the_previous_success_timestamp():
    state = {"fail": False}

    def poll_fn():
        if state["fail"]:
            return [], Diagnostics(
                endpoint_status="http_error",
                http_status_code=500,
                parser_error="HTTP 500",
            )
        return [_match(SPORTPESA, 2.10, 3.30, 3.40, event_id="sp")], _ok()

    worker = BaseKenyanWorker(
        "SportPesa_prematch",
        poll_fn,
        poll_interval_seconds=30,
        retention_seconds=180,
    )
    worker._run_one_cycle()
    success_at = worker.get_status()["last_successful_poll_at"]
    confirmed = worker.get_matches()[0].confirmed_at
    state["fail"] = True
    worker._run_one_cycle()
    status = worker.get_status()
    assert status["last_successful_poll_at"] == success_at
    assert worker.get_matches()[0].confirmed_at == confirmed
    assert worker.get_matches()[0].home_odds == 2.10
    assert status["poll_status"] == "failed"
    assert status["last_poll_error"] == "HTTP 500"
    assert status["last_response_status"] == 500


def test_slow_bookmaker_does_not_block_another_or_overlap_itself():
    slow_calls = []
    fast_calls = []
    slow_active = {"n": 0, "max": 0}

    def slow():
        slow_active["n"] += 1
        slow_active["max"] = max(slow_active["max"], slow_active["n"])
        slow_calls.append(time.monotonic())
        time.sleep(0.25)
        slow_active["n"] -= 1
        return [_match(SPORTPESA, 2.10, 3.30, 3.40, event_id="sp")], _ok()

    def fast():
        fast_calls.append(time.monotonic())
        return [_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")], _ok()

    slow_worker = BaseKenyanWorker("SportPesa_prematch", slow, poll_interval_seconds=0.05)
    fast_worker = BaseKenyanWorker("Betika_prematch", fast, poll_interval_seconds=0.05)
    slow_worker.start()
    fast_worker.start()
    try:
        time.sleep(0.4)
    finally:
        slow_worker.stop()
        fast_worker.stop()

    assert slow_active["max"] == 1
    assert len(fast_calls) >= 3
    assert len(slow_calls) >= 1
    assert len(fast_calls) > len(slow_calls)
    assert slow_worker.get_status()["missed_poll_interval"] is True


def test_overlapping_poll_of_the_same_worker_is_skipped():
    entered = {"n": 0}

    def poll_fn():
        entered["n"] += 1
        worker._poll_in_flight = True
        return [_match(SPORTPESA, 2.10, 3.30, 3.40, event_id="sp")], _ok()

    worker = BaseKenyanWorker("SportPesa_prematch", poll_fn, poll_interval_seconds=30)
    worker._run_one_cycle()
    worker._poll_in_flight = True
    worker._run_one_cycle()
    assert entered["n"] == 1
    assert worker._poll_count == 1


def test_in_flight_poll_does_not_make_stale_odds_eligible():
    def poll_fn():
        return _pair(), _ok(events_discovered=2, valid_normalized_events=2)

    left = BaseKenyanWorker("SportPesa_prematch", lambda: (poll_fn()[0][:1], _ok()), poll_interval_seconds=90, retention_seconds=180)
    right = BaseKenyanWorker("Betika_prematch", lambda: (poll_fn()[0][1:], _ok()), poll_interval_seconds=90, retention_seconds=180)
    left._run_one_cycle()
    right._run_one_cycle()
    aged = time.time() - (KENYAN_PREMATCH_STALE_AFTER_SECONDS + 30)
    aged_dt = datetime.fromtimestamp(aged, tz=timezone.utc)
    for worker in (left, right):
        worker._last_good_at = aged
        worker._last_successful_poll_at = aged
        for record in worker._match_records.values():
            record.last_seen = aged
            record.match.collected_at = aged_dt
            record.match.confirmed_at = aged_dt
        worker._poll_in_flight = True
    stored = list(left._match_records.values())[0].match.confirmed_at
    matches = left.get_matches() + right.get_matches()
    assert len(matches) == 2
    assert matches[0].confirmed_at == stored
    assert KenyanArbitrageEngine().compute_opportunities(matches, now=datetime.now(timezone.utc)) == []
    assert left.get_status()["poll_status"] == "stale"


def test_stale_prematch_odds_are_excluded_from_arbitrage():
    old = NOW - timedelta(seconds=KENYAN_PREMATCH_STALE_AFTER_SECONDS + 5)
    assert KenyanArbitrageEngine().compute_opportunities(_pair(collected_at=old), now=NOW) == []
    assert KenyanArbitrageEngine().compute_opportunities(_pair(collected_at=NOW), now=NOW)


def test_api_status_and_opportunities_follow_the_latest_successful_snapshot():
    prices = {"home": 2.10}

    def sportpesa_poll():
        return [_match(SPORTPESA, prices["home"], 3.30, 3.40, event_id="sp")], _ok()

    def betika_poll():
        return [_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")], _ok()

    sportpesa_worker = BaseKenyanWorker(
        "SportPesa_prematch", sportpesa_poll, poll_interval_seconds=90, retention_seconds=180
    )
    betika_worker = BaseKenyanWorker(
        "Betika_prematch", betika_poll, poll_interval_seconds=90, retention_seconds=180
    )
    sportpesa_worker._run_one_cycle()
    betika_worker._run_one_cycle()

    runner = KenyanEngineRunner()
    runner._workers = {
        "SportPesa_prematch": sportpesa_worker,
        "Betika_prematch": betika_worker,
    }
    runner._started = True
    runner._refresh_opportunities(
        PREMATCH,
        runner._prematch_engine,
        runner._prematch_store,
        runner._prematch_compute_lock,
        "_prematch_cache",
        "_prematch_compute_seq",
        "_prematch_applied_seq",
    )
    first = runner.get_prematch_opportunities()
    assert len(first) == 1
    assert first[0].opportunity.result.best_odds.home_odds == 2.10

    prices["home"] = 2.80
    sportpesa_worker._run_one_cycle()
    runner._refresh_opportunities(
        PREMATCH,
        runner._prematch_engine,
        runner._prematch_store,
        runner._prematch_compute_lock,
        "_prematch_cache",
        "_prematch_compute_seq",
        "_prematch_applied_seq",
    )
    second = runner.get_prematch_opportunities()
    assert len(second) == 1
    assert second[0].opportunity.result.best_odds.home_odds == 2.80

    status = runner.get_engine_status()["workers"]["SportPesa_prematch"]
    assert status["poll_interval_seconds"] == 90
    assert status["poll_status"] == "fresh"
    assert status["last_poll_started_at"] is not None
    assert status["last_successful_poll_at"] is not None
    assert status["poll_duration_seconds"] is not None
    assert status["events_retrieved"] == 1
    assert status["odds_parsed"] == 1
    assert status["last_poll_error"] is None

    for worker in (sportpesa_worker, betika_worker):
        aged = time.time() - (KENYAN_PREMATCH_STALE_AFTER_SECONDS + 5)
        aged_dt = datetime.fromtimestamp(aged, tz=timezone.utc)
        worker._last_successful_poll_at = aged
        for record in worker._match_records.values():
            record.match.confirmed_at = aged_dt
            record.match.collected_at = aged_dt
    runner._refresh_opportunities(
        PREMATCH,
        runner._prematch_engine,
        runner._prematch_store,
        runner._prematch_compute_lock,
        "_prematch_cache",
        "_prematch_compute_seq",
        "_prematch_applied_seq",
    )
    assert runner.get_prematch_opportunities() == []
