"""LIVE concurrency, skip-unchanged, and processing independence."""
import threading
import time
from datetime import datetime, timezone

from kenyan.config import BETIKA, KENYAN_LIVE_POLL_INTERVAL_SECONDS, ONEXBET, SPORTPESA
from kenyan.engine import KenyanArbitrageEngine
from kenyan.http_utils import FetchResult, copy_cache_headers
from kenyan.models import KenyanMatchOdds
from kenyan.runner import KenyanEngineRunner
from kenyan.workers.base import BaseKenyanWorker, Diagnostics


NOW = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)


def _match(bookmaker, home_odds=2.10, draw_odds=3.30, away_odds=3.40, event_id="1"):
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="Alpha",
        away_team="Beta",
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
        event_id=event_id,
        status="LIVE",
    )


def _ok(matches):
    return matches, Diagnostics(endpoint_status="ok", valid_normalized_events=len(matches))


def test_live_poll_interval_is_two_seconds_not_fifteen():
    assert KENYAN_LIVE_POLL_INTERVAL_SECONDS == 2


def test_slow_live_bookmaker_does_not_block_others():
    started = {}
    finished = {}

    def slow():
        started["slow"] = time.monotonic()
        time.sleep(0.35)
        finished["slow"] = time.monotonic()
        return _ok([_match(SPORTPESA, event_id="sp")])

    def fast():
        started["fast"] = time.monotonic()
        finished["fast"] = time.monotonic()
        return _ok([_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")])

    slow_worker = BaseKenyanWorker("slow_live", slow, poll_interval_seconds=10)
    fast_worker = BaseKenyanWorker("fast_live", fast, poll_interval_seconds=10)
    slow_thread = threading.Thread(target=slow_worker._run_one_cycle)
    fast_thread = threading.Thread(target=fast_worker._run_one_cycle)
    slow_thread.start()
    fast_thread.start()
    fast_thread.join(timeout=1)
    assert fast_worker.get_matches()
    assert "slow" not in finished
    slow_thread.join(timeout=1)
    assert slow_worker.get_matches()
    assert finished["fast"] < finished["slow"]


def test_duplicate_live_poll_is_prevented():
    calls = {"n": 0}
    entered = threading.Event()
    release = threading.Event()

    def poll_fn():
        calls["n"] += 1
        entered.set()
        release.wait(timeout=1)
        return _ok([_match(SPORTPESA)])

    worker = BaseKenyanWorker("dup_live", poll_fn, poll_interval_seconds=10)
    first = threading.Thread(target=worker._run_one_cycle)
    first.start()
    assert entered.wait(timeout=1)
    worker._run_one_cycle()
    release.set()
    first.join(timeout=1)
    assert calls["n"] == 1


def test_failed_bookmaker_does_not_stop_other_live_workers():
    def boom():
        raise RuntimeError("bookmaker down")

    broken = BaseKenyanWorker("broken_live", boom, poll_interval_seconds=10)
    ok = BaseKenyanWorker(
        "ok_live",
        lambda: _ok([_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")]),
        poll_interval_seconds=10,
    )
    broken._run_one_cycle()
    ok._run_one_cycle()
    assert broken.get_matches() == []
    assert len(ok.get_matches()) == 1
    assert ok.get_status()["diagnostics"]["endpoint_status"] == "ok"


def test_live_compute_skips_unchanged_snapshots():
    runner = KenyanEngineRunner()
    calls = {"n": 0}

    def compute(matches, **_kwargs):
        calls["n"] += 1
        return KenyanArbitrageEngine().compute_opportunities(matches, now=NOW)

    runner._live_engine.compute_opportunities = compute
    left = BaseKenyanWorker(
        "1xBet_live",
        lambda: _ok([_match(ONEXBET, event_id="1x")]),
        poll_interval_seconds=100,
    )
    right = BaseKenyanWorker(
        "Betika_live",
        lambda: _ok([_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")]),
        poll_interval_seconds=100,
    )
    left._run_one_cycle()
    right._run_one_cycle()
    runner._workers = {"1xBet_live": left, "Betika_live": right}

    runner._refresh_live_opportunities()
    first = calls["n"]
    assert first == 1
    runner._refresh_live_opportunities()
    assert calls["n"] == first
    assert runner._live_last_process["skipped_unchanged"] is True
    assert runner._live_last_process["process_ms"] < 1000


def test_live_compute_is_independent_of_prematch_queue():
    runner = KenyanEngineRunner()
    live = BaseKenyanWorker(
        "Betika_live",
        lambda: _ok([_match(BETIKA, 2.00, 3.90, 4.00, event_id="bk")]),
        poll_interval_seconds=100,
    )
    live._run_one_cycle()
    runner._workers = {"Betika_live": live}

    blocked = threading.Event()

    def hang(*_args, **_kwargs):
        blocked.wait(timeout=2)
        raise AssertionError("prematch compute must not run for LIVE refresh")

    runner._prematch_engine.compute_opportunities = hang
    runner._refresh_live_opportunities()
    assert runner._live_last_process["match_count"] == 1
    assert blocked.is_set() is False


def test_live_snapshot_callback_wakes_compute_without_waiting_idle():
    runner = KenyanEngineRunner()
    woken = []

    def on_ready():
        woken.append(time.monotonic())

    worker = BaseKenyanWorker(
        "SportPesa_live",
        lambda: _ok([_match(SPORTPESA)]),
        poll_interval_seconds=100,
    )
    worker.set_on_snapshot(on_ready)
    worker._run_one_cycle()
    assert woken
    runner._notify_live_ready()
    assert runner._live_ready.is_set()


def test_http_cache_headers_copy_onto_diagnostics():
    fetch = FetchResult(
        url="https://example.test",
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=12,
        elapsed_seconds=0.04,
        json_body={"ok": True},
        http_date="Mon, 12 Oct 2026 01:00:00 GMT",
        cache_age="2",
        etag='"v1"',
        last_modified="Mon, 12 Oct 2026 00:59:50 GMT",
        cache_control="max-age=1",
    )
    diagnostics = copy_cache_headers(Diagnostics(endpoint_status="ok"), fetch)
    assert diagnostics.http_date == fetch.http_date
    assert diagnostics.cache_age == "2"
    assert diagnostics.etag == '"v1"'
    assert diagnostics.last_modified == fetch.last_modified
    assert diagnostics.cache_control == "max-age=1"


def test_live_status_exposes_process_metrics():
    runner = KenyanEngineRunner()
    runner._refresh_live_opportunities()
    status = runner.get_engine_status()
    assert "live_pipeline" in status
    assert "process_ms" in status["live_pipeline"]
    assert "gather_ms" in status["live_pipeline"]
    assert "skipped_unchanged" in status["live_pipeline"]
