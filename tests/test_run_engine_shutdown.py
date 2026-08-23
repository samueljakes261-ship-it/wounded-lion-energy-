"""
Verifies run_engine.py's shutdown path without needing a real Ctrl+C /
OS signal (unreliable to deliver to a background process in CI): we
run main() as an asyncio Task, cancel it (the same exception asyncio
delivers on Ctrl+C), and assert both persistent workers are stopped
exactly once and no exception escapes.
"""

import asyncio

import pytest

import run_engine


@pytest.fixture
def anyio_backend():
    # anyio's pytest plugin (already a transitive dependency via
    # starlette/FastAPI) is used here instead of adding a new
    # pytest-asyncio dependency just for these two tests.
    return "asyncio"


@pytest.mark.anyio
async def test_cancelling_main_stops_all_three_workers_cleanly(monkeypatch):
    calls = {
        "start": 0, "stop_onwin": 0, "stop_betkanyon": 0, "stop_orbit": 0,
        "ticks": 0,
    }

    def fake_start_workers():
        calls["start"] += 1

    def fake_stop_onwin():
        calls["stop_onwin"] += 1

    def fake_stop_betkanyon():
        calls["stop_betkanyon"] += 1

    async def fake_stop_orbit():
        calls["stop_orbit"] += 1

    async def fake_collect_opportunities(*args, **kwargs):
        calls["ticks"] += 1
        return []

    monkeypatch.setattr(run_engine, "start_workers", fake_start_workers)
    monkeypatch.setattr(run_engine, "start_prematch_workers", lambda: None)
    monkeypatch.setattr(run_engine, "stop_onwin_worker", fake_stop_onwin)
    monkeypatch.setattr(run_engine, "stop_betkanyon_worker", fake_stop_betkanyon)
    monkeypatch.setattr(run_engine, "stop_orbit_worker", fake_stop_orbit)
    monkeypatch.setattr(run_engine, "stop_betkanyon_prematch_worker", lambda: None)

    async def fake_stop_orbit_prematch():
        return None

    monkeypatch.setattr(run_engine, "stop_orbit_prematch_worker", fake_stop_orbit_prematch)

    stop_onwin_prematch = {"n": 0}

    monkeypatch.setattr(
        run_engine,
        "stop_onwin_prematch_worker",
        lambda: stop_onwin_prematch.__setitem__("n", stop_onwin_prematch["n"] + 1),
    )
    monkeypatch.setattr(run_engine, "collect_opportunities", fake_collect_opportunities)
    monkeypatch.setattr(run_engine, "ENGINE_TICK_SECONDS", 0.01)

    task = asyncio.create_task(run_engine.main())

    # Let a few ticks happen so we know the loop is genuinely running,
    # not just starting up.
    for _ in range(20):
        if calls["ticks"] >= 2:
            break
        await asyncio.sleep(0.01)

    assert calls["ticks"] >= 2
    assert calls["start"] == 1

    # This is what happens on Ctrl+C: asyncio delivers CancelledError
    # into whatever `await` main() is currently blocked on.
    task.cancel()

    await asyncio.wait_for(task, timeout=2)

    assert calls["stop_onwin"] == 1
    assert calls["stop_betkanyon"] == 1
    assert calls["stop_orbit"] == 1
    assert stop_onwin_prematch["n"] == 1
    assert task.cancelled() is False  # main() caught it and returned normally


@pytest.mark.anyio
async def test_engine_error_in_one_tick_does_not_crash_the_loop(monkeypatch):
    """An exception from one collect_opportunities() call must be
    logged and swallowed, not kill the whole engine loop."""

    calls = {"ticks": 0, "stop_onwin": 0, "stop_betkanyon": 0, "stop_orbit": 0}

    async def flaky_collect_opportunities(*args, **kwargs):
        calls["ticks"] += 1
        if calls["ticks"] == 1:
            raise RuntimeError("simulated transient engine error")
        return []

    async def fake_stop_orbit():
        calls["stop_orbit"] += 1

    monkeypatch.setattr(run_engine, "start_workers", lambda: None)
    monkeypatch.setattr(run_engine, "start_prematch_workers", lambda: None)
    monkeypatch.setattr(
        run_engine, "stop_onwin_worker",
        lambda: calls.__setitem__("stop_onwin", calls["stop_onwin"] + 1),
    )
    monkeypatch.setattr(
        run_engine, "stop_betkanyon_worker",
        lambda: calls.__setitem__("stop_betkanyon", calls["stop_betkanyon"] + 1),
    )
    monkeypatch.setattr(run_engine, "stop_orbit_worker", fake_stop_orbit)
    monkeypatch.setattr(run_engine, "stop_betkanyon_prematch_worker", lambda: None)

    async def fake_stop_orbit_prematch():
        return None

    monkeypatch.setattr(run_engine, "stop_orbit_prematch_worker", fake_stop_orbit_prematch)
    monkeypatch.setattr(run_engine, "stop_onwin_prematch_worker", lambda: None)
    monkeypatch.setattr(run_engine, "collect_opportunities", flaky_collect_opportunities)
    monkeypatch.setattr(run_engine, "ENGINE_TICK_SECONDS", 0.01)

    task = asyncio.create_task(run_engine.main())

    for _ in range(30):
        if calls["ticks"] >= 3:
            break
        await asyncio.sleep(0.01)

    assert calls["ticks"] >= 3  # survived the RuntimeError on tick 1

    task.cancel()
    await asyncio.wait_for(task, timeout=2)

    assert calls["stop_onwin"] == 1
    assert calls["stop_betkanyon"] == 1
    assert calls["stop_orbit"] == 1
