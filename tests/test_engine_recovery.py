"""Scheduled restart and last-good snapshot tests. No live browsers."""

from __future__ import annotations

import asyncio

import pytest

from engine.recovery import (
    begin_scheduled_restart,
    display_collector_status,
    end_scheduled_restart,
    restart_due,
    scheduled_restart_active,
    should_replace_snapshot,
)


def test_scheduled_restart_interval_is_ten_minutes():
    from engine.recovery import ENGINE_RESTART_SECONDS

    assert ENGINE_RESTART_SECONDS == 600
    assert restart_due(0, now=599) is False
    assert restart_due(0, now=600) is True


def test_empty_acquisition_does_not_clear_last_good():
    assert should_replace_snapshot([], previous_count=4, feeds_ready=False) is False
    assert should_replace_snapshot([], previous_count=4, feeds_ready=True) is False


def test_partial_acquisition_does_not_replace_last_good():
    assert should_replace_snapshot([{"id": 1}], previous_count=8, feeds_ready=False) is False


def test_valid_ready_snapshot_replaces_last_good():
    assert should_replace_snapshot([{"id": 1}, {"id": 2}], previous_count=8, feeds_ready=True) is True


def test_first_snapshot_can_be_written():
    assert should_replace_snapshot([{"id": 1}], previous_count=0, feeds_ready=True) is True


def test_scheduled_restart_status_looks_running():
    begin_scheduled_restart()
    try:
        assert scheduled_restart_active() is True
        assert display_collector_status("STARTING", True) == "RUNNING"
        assert display_collector_status("STOPPED", True) == "RUNNING"
        assert display_collector_status("RECOVERING", True) == "RUNNING"
        assert display_collector_status("ERROR", True) == "ERROR"
        assert display_collector_status("DEGRADED", True) == "DEGRADED"
    finally:
        end_scheduled_restart()
    assert scheduled_restart_active() is False
    assert display_collector_status("STARTING", False) == "STARTING"


@pytest.mark.anyio
async def test_repeated_restart_stops_before_start(monkeypatch):
    import run_engine

    calls = []

    def stop_sync():
        calls.append("stop")

    async def stop_async():
        calls.append("stop")

    def start():
        calls.append("start")
        assert calls.count("stop") >= calls.count("start")

    monkeypatch.setattr(run_engine, "stop_onwin_worker", stop_sync)
    monkeypatch.setattr(run_engine, "stop_betkanyon_worker", stop_sync)
    monkeypatch.setattr(run_engine, "stop_orbit_worker", stop_async)
    monkeypatch.setattr(run_engine, "stop_betkanyon_prematch_worker", stop_sync)
    monkeypatch.setattr(run_engine, "stop_orbit_prematch_worker", stop_async)
    monkeypatch.setattr(run_engine, "stop_kolay90_prematch_worker", stop_sync)
    monkeypatch.setattr(run_engine, "stop_onwin_prematch_worker", stop_sync)
    monkeypatch.setattr(run_engine, "start_workers", start)
    monkeypatch.setattr(run_engine, "start_prematch_workers", start)
    monkeypatch.setattr(run_engine, "is_prematch_only", lambda: True)

    await run_engine.restart_workers_gracefully()
    await run_engine.restart_workers_gracefully()
    assert calls.count("start") == 2
    assert calls[0] == "stop"
    assert calls[-1] == "start"


def test_kolay90_close_does_not_launch_or_kill_chrome():
    from parsers.kolay90_prematch.feed import Kolay90PrematchFeed

    feed = Kolay90PrematchFeed()
    feed._page = object()
    feed._playwright = None
    feed.close()
    assert feed._page is None
