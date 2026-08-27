"""
Collector independence + dead-worker supervision.

Proves that:
- each collector starts independently
- a failure constructing/starting one worker does not stop the others
- a worker that exits unexpectedly is restarted
- generic worker death is not left as permanent IDLE
- opportunity count still does not control collector status

No network/browser: workers are fakes.
"""

import pytest

import collector
from tests.test_engine_collector_independence import (
    FakeBetkanyonWorker,
    FakeOnwinHandle,
    FakeOrbitWorker,
    _isolate_files,
    _patch_workers,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_start_workers_continues_when_onwin_constructor_raises(monkeypatch):
    started = {"betkanyon": False, "orbit": False}
    monkeypatch.setenv("ONWIN_LIVE", "1")

    def boom():
        raise RuntimeError("onwin constructor failed")

    def start_betkanyon():
        started["betkanyon"] = True
        return FakeBetkanyonWorker()

    def start_orbit():
        started["orbit"] = True
        return FakeOrbitWorker()

    monkeypatch.setattr(collector, "_get_onwin_handle", boom)
    monkeypatch.setattr(collector, "_get_betkanyon_worker", start_betkanyon)
    monkeypatch.setattr(collector, "_get_orbit_worker", start_orbit)

    collector.start_workers()

    assert started["betkanyon"] is True
    assert started["orbit"] is True


def test_start_workers_does_not_start_onwin_live_by_default(monkeypatch):
    started = {"onwin": False, "betkanyon": False, "orbit": False}
    monkeypatch.delenv("ONWIN_LIVE", raising=False)
    monkeypatch.setattr(
        collector, "_get_onwin_handle",
        lambda: started.__setitem__("onwin", True) or FakeOnwinHandle(),
    )
    monkeypatch.setattr(
        collector, "_get_betkanyon_worker",
        lambda: started.__setitem__("betkanyon", True) or FakeBetkanyonWorker(),
    )
    monkeypatch.setattr(
        collector, "_get_orbit_worker",
        lambda: started.__setitem__("orbit", True) or FakeOrbitWorker(),
    )
    collector.start_workers()
    assert started["onwin"] is False
    assert started["betkanyon"] is True
    assert started["orbit"] is True


def test_start_workers_starts_onwin_live_when_enabled(monkeypatch):
    started = {"onwin": False, "betkanyon": False, "orbit": False}
    monkeypatch.setenv("ONWIN_LIVE", "1")
    monkeypatch.setattr(
        collector, "_get_onwin_handle",
        lambda: started.__setitem__("onwin", True) or FakeOnwinHandle(),
    )
    monkeypatch.setattr(
        collector, "_get_betkanyon_worker",
        lambda: started.__setitem__("betkanyon", True) or FakeBetkanyonWorker(),
    )
    monkeypatch.setattr(
        collector, "_get_orbit_worker",
        lambda: started.__setitem__("orbit", True) or FakeOrbitWorker(),
    )
    collector.start_workers()
    assert started["onwin"] is True
    assert started["betkanyon"] is True
    assert started["orbit"] is True


def test_start_workers_continues_when_betkanyon_constructor_raises(monkeypatch):
    started = {"onwin": False, "orbit": False}
    monkeypatch.setenv("ONWIN_LIVE", "1")

    monkeypatch.setattr(
        collector, "_get_onwin_handle", lambda: started.__setitem__("onwin", True) or FakeOnwinHandle()
    )
    monkeypatch.setattr(
        collector, "_get_betkanyon_worker", lambda: (_ for _ in ()).throw(RuntimeError("bk failed"))
    )
    monkeypatch.setattr(
        collector, "_get_orbit_worker", lambda: started.__setitem__("orbit", True) or FakeOrbitWorker()
    )

    collector.start_workers()

    assert started["onwin"] is True
    assert started["orbit"] is True


def test_start_workers_continues_when_orbit_constructor_raises(monkeypatch):
    started = {"onwin": False, "betkanyon": False}
    monkeypatch.setenv("ONWIN_LIVE", "1")

    monkeypatch.setattr(
        collector, "_get_onwin_handle", lambda: started.__setitem__("onwin", True) or FakeOnwinHandle()
    )
    monkeypatch.setattr(
        collector,
        "_get_betkanyon_worker",
        lambda: started.__setitem__("betkanyon", True) or FakeBetkanyonWorker(),
    )
    monkeypatch.setattr(
        collector, "_get_orbit_worker", lambda: (_ for _ in ()).throw(RuntimeError("orbit failed"))
    )

    collector.start_workers()

    assert started["onwin"] is True
    assert started["betkanyon"] is True


def test_start_prematch_workers_starts_onwin_prematch_not_live(monkeypatch):
    started = {}
    monkeypatch.delenv("ONWIN_LIVE", raising=False)

    monkeypatch.setattr(
        collector,
        "_get_betkanyon_prematch_worker",
        lambda: started.__setitem__("bk_pm", True) or object(),
    )
    monkeypatch.setattr(
        collector,
        "_get_orbit_prematch_worker",
        lambda: started.__setitem__("orbit_pm", True) or object(),
    )
    monkeypatch.setattr(
        collector,
        "_get_onwin_prematch_worker",
        lambda: started.__setitem__("onwin_pm", True) or object(),
    )
    monkeypatch.setattr(
        collector,
        "_get_kolay90_prematch_worker",
        lambda: started.__setitem__("kolay90_pm", True) or object(),
    )
    monkeypatch.setattr(
        collector,
        "_get_onwin_handle",
        lambda: started.__setitem__("onwin_live", True) or FakeOnwinHandle(),
    )
    collector.start_prematch_workers()
    assert started == {
        "bk_pm": True,
        "orbit_pm": True,
        "onwin_pm": True,
        "kolay90_pm": True,
    }


@pytest.mark.anyio
async def test_dead_onwin_worker_is_restarted_without_stopping_others(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    monkeypatch.setattr(collector, "_WORKER_RESTART_MIN_INTERVAL_SECONDS", 0)

    onwin = FakeOnwinHandle(matches=[], alive=False)
    betkanyon = FakeBetkanyonWorker(matches=[])
    orbit = FakeOrbitWorker(matches=[])

    restarts = {"onwin": 0}

    def restart_onwin():
        restarts["onwin"] += 1
        replacement = FakeOnwinHandle(matches=[], alive=True)
        monkeypatch.setattr(collector, "_onwin_handle", replacement)
        return replacement

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)
    monkeypatch.setattr(collector, "_get_onwin_handle", restart_onwin)

    await collector.collect_opportunities()

    assert restarts["onwin"] >= 1
    status = collector.get_collector_status()
    assert status["collectors"]["betkanyon"]["collectorStatus"] in ("RUNNING", "STARTING")
    assert status["collectors"]["orbit"]["collectorStatus"] in ("RUNNING", "STARTING")
    assert status["collectors"]["onwin"]["workerAlive"] is True


@pytest.mark.anyio
async def test_dead_betkanyon_worker_is_restarted_without_stopping_orbit(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)
    monkeypatch.setattr(collector, "_WORKER_RESTART_MIN_INTERVAL_SECONDS", 0)

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=[], alive=False)
    orbit = FakeOrbitWorker(matches=[])

    restarts = {"betkanyon": 0}

    def restart_bk():
        restarts["betkanyon"] += 1
        replacement = FakeBetkanyonWorker(matches=[], alive=True)
        monkeypatch.setattr(collector, "_betkanyon_worker", replacement)
        return replacement

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)
    monkeypatch.setattr(collector, "_get_betkanyon_worker", restart_bk)

    await collector.collect_opportunities()

    assert restarts["betkanyon"] >= 1
    status = collector.get_collector_status()
    assert status["collectors"]["orbit"]["collectorStatus"] in ("RUNNING", "STARTING")
    assert status["collectors"]["onwin"]["collectorStatus"] in ("RUNNING", "STARTING")
    assert status["collectors"]["betkanyon"]["workerAlive"] is True


@pytest.mark.anyio
async def test_status_snapshot_exposes_worker_alive_and_error_fields(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=[])
    orbit = FakeOrbitWorker(matches=[])
    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    await collector.collect_opportunities()

    status = collector.get_collector_status()
    orbit_snap = status["collectors"]["orbit"]
    for field in (
        "workerAlive",
        "lastAttempt",
        "lastSuccess",
        "lastError",
        "lastErrorType",
        "consecutiveFailures",
        "consecutiveSuccesses",
        "reconnectCount",
        "dataAge",
        "recordsCollected",
        "phase",
    ):
        assert field in orbit_snap

    assert orbit_snap["workerAlive"] is True
    assert "apikey=" not in str(status).lower()
    assert "MASTER_CREDENTIAL_KEY" not in str(status)
