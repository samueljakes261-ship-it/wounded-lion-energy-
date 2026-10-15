"""
Issue 2 regression coverage: "0 opportunities" must never be
interpreted as "a collector stopped". These tests drive the REAL
collect_opportunities() tick end-to-end (matching + arbitrage +
cache/status writing) with fake OnWin/BetKanyon/Orbit workers so no
network/browser/websocket access happens.

Covers testing requirements 8-14 from the task spec:
  8.  Orbit remains RUNNING when opportunities == 0.
  9.  Orbit collector continues collecting when no arbitrage exists.
  10. BetKanyon remains independent of Orbit's opportunity count.
  11. Orbit + BetKanyon can produce an opportunity when odds create one.
  12. Orbit + BetKanyon correctly produce zero opportunities otherwise.
  13. Collector health status remains RUNNING when opportunities == 0.
  14. Collector failure is distinguished from zero opportunities.
"""

from datetime import datetime, timezone

import pytest

import collector
from models.match import MatchOdds


NOW = datetime.now(timezone.utc)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _AliveHandle:
    """Minimal stand-in for whatever _write_status()'s _worker_alive()
    inspects (process/thread/task)."""

    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive

    def done(self):
        return not self._alive


class FakeOnwinHandle:
    def __init__(self, matches=None, raw_status="running", alive=True):
        self._matches = matches or []
        self._process = _AliveHandle(alive)
        self._status = raw_status

    def status(self):
        return {
            "matches": list(self._matches),
            "event_count": len(self._matches),
            "status": self._status,
            "error": None,
            "last_update_at": time_now(),
        }

    def get_matches(self):
        return list(self._matches)

    def stop(self, timeout=10):
        pass


class FakeBetkanyonWorker:
    def __init__(self, matches=None, raw_status="running", alive=True):
        self._matches = matches or []
        self._thread = _AliveHandle(alive)
        self._status = raw_status

    def get_status(self):
        return {
            "matches": list(self._matches),
            "status": self._status,
            "error": None,
            "last_update_at": time_now(),
            "last_attempt_at": time_now(),
            "last_event_count": len(self._matches),
        }

    def get_matches(self):
        return list(self._matches)

    def stop(self, timeout=10):
        pass


class FakeOrbitWorker:
    def __init__(self, matches=None, raw_status="running", alive=True):
        self._matches = matches or []
        self._task = _AliveHandle(alive)
        self._status = raw_status

    def get_status(self):
        return {
            "matches": list(self._matches),
            "status": self._status,
            "error": None,
            "last_update_at": time_now(),
            "last_attempt_at": time_now(),
            "market_count": len(self._matches),
        }

    def get_matches(self):
        return list(self._matches)

    async def stop(self, timeout=10):
        pass


def time_now():
    import time
    return time.time()


def onwin_match(home, away, ho, do, ao):
    return MatchOdds(
        bookmaker="OnWin", competition="X", sport="football", market="1X2",
        home_team=home, away_team=away,
        home_odds=ho, draw_odds=do, away_odds=ao,
        start_time=NOW, collected_at=datetime.now(timezone.utc),
    )


def betkanyon_match(home, away, ho, do, ao):
    return MatchOdds(
        bookmaker="Betkanyon", competition="X", sport="football", market="Match Odds",
        home_team=home, away_team=away,
        home_odds=ho, draw_odds=do, away_odds=ao,
        start_time=NOW, collected_at=datetime.now(timezone.utc),
    )


def orbit_match(home, away, ho, do, ao, side="BACK"):
    return MatchOdds(
        bookmaker="Orbit", competition="X", sport="football", market="Match Odds",
        home_team=home, away_team=away,
        home_odds=ho, draw_odds=do, away_odds=ao,
        start_time=NOW, collected_at=datetime.now(timezone.utc), side=side,
    )


def _patch_workers(monkeypatch, onwin, betkanyon, orbit):
    monkeypatch.setattr(collector, "_get_onwin_handle", lambda: onwin)
    monkeypatch.setattr(collector, "_get_betkanyon_worker", lambda: betkanyon)
    monkeypatch.setattr(collector, "_get_orbit_worker", lambda: orbit)
    # _write_status() reads the module-level singletons directly (for
    # process/thread/task liveness), not just the getters.
    monkeypatch.setattr(collector, "_onwin_handle", onwin)
    monkeypatch.setattr(collector, "_betkanyon_worker", betkanyon)
    monkeypatch.setattr(collector, "_orbit_worker", orbit)


def _isolate_files(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(collector, "STATUS_FILE", tmp_path / "status.json")
    # Fresh engine-monitor state per test (module-level dict persists
    # across calls in production on purpose, but tests must not leak
    # "triggered"/heartbeat state between each other).
    monkeypatch.setitem(collector._engine_monitor, "last_onwin_update_at", None)
    monkeypatch.setitem(collector._engine_monitor, "last_betkanyon_update_at", None)
    monkeypatch.setitem(collector._engine_monitor, "last_orbit_update_at", None)


@pytest.mark.anyio
async def test_orbit_running_with_zero_opportunities(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    # Orbit has live data but nothing that matches any other bookmaker
    # -- zero opportunities is the CORRECT engine output here.
    orbit_matches = [orbit_match("Napoli", "Roma", 2.10, 3.30, 3.50)]

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=[])
    orbit = FakeOrbitWorker(matches=orbit_matches)

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    opportunities = await collector.collect_opportunities()

    assert opportunities == []

    status = collector.get_collector_status()
    assert status["opportunityCount"] == 0
    assert status["collectors"]["orbit"]["collectorStatus"] == "RUNNING"


@pytest.mark.anyio
async def test_betkanyon_independent_of_orbit_opportunity_count(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    betkanyon_matches = [betkanyon_match("Liverpool", "Chelsea", 2.0, 3.3, 3.6)]

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=betkanyon_matches)
    orbit = FakeOrbitWorker(matches=[])  # Orbit has nothing at all right now

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    opportunities = await collector.collect_opportunities()
    assert opportunities == []

    status = collector.get_collector_status()
    assert status["collectors"]["betkanyon"]["collectorStatus"] == "RUNNING"
    assert status["collectors"]["orbit"]["collectorStatus"] == "RUNNING"


@pytest.mark.anyio
async def test_opportunity_appears_dynamically_when_odds_create_one(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    betkanyon_matches = [betkanyon_match("Liverpool", "Chelsea", 2.30, 3.00, 3.00)]
    orbit_matches = [orbit_match("Liverpool", "Chelsea", 1.90, 3.80, 4.20, side="BACK")]

    implied = (1 / 2.30) + (1 / 3.80) + (1 / 4.20)
    assert implied < 1, "fixture must contain a genuine arbitrage"

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=betkanyon_matches)
    orbit = FakeOrbitWorker(matches=orbit_matches)

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    opportunities = await collector.collect_opportunities()

    assert len(opportunities) == 1

    status = collector.get_collector_status()
    assert status["opportunityCount"] == 1
    assert status["collectors"]["orbit"]["collectorStatus"] == "RUNNING"
    assert status["collectors"]["betkanyon"]["collectorStatus"] == "RUNNING"


@pytest.mark.anyio
async def test_fair_odds_produce_zero_opportunities_with_healthy_collectors(tmp_path, monkeypatch):
    _isolate_files(tmp_path, monkeypatch)

    betkanyon_matches = [betkanyon_match("Liverpool", "Chelsea", 1.95, 3.25, 3.70)]
    orbit_matches = [orbit_match("Liverpool", "Chelsea", 1.90, 3.20, 3.65, side="BACK")]

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=betkanyon_matches)
    orbit = FakeOrbitWorker(matches=orbit_matches)

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    opportunities = await collector.collect_opportunities()

    assert opportunities == []

    status = collector.get_collector_status()
    assert status["opportunityCount"] == 0
    assert status["collectors"]["orbit"]["collectorStatus"] == "RUNNING"
    assert status["collectors"]["betkanyon"]["collectorStatus"] == "RUNNING"


@pytest.mark.anyio
async def test_collector_failure_is_distinguished_from_zero_opportunities(tmp_path, monkeypatch):
    """A genuinely dead Orbit worker (task finished unexpectedly, not
    via stop()) must show ERROR, not be confused with "just no
    opportunities right now"."""
    _isolate_files(tmp_path, monkeypatch)

    onwin = FakeOnwinHandle(matches=[])
    betkanyon = FakeBetkanyonWorker(matches=[])
    orbit = FakeOrbitWorker(matches=[], raw_status="running", alive=False)

    _patch_workers(monkeypatch, onwin, betkanyon, orbit)

    opportunities = await collector.collect_opportunities()

    assert opportunities == []

    status = collector.get_collector_status()
    # Zero opportunities AND a genuinely dead worker must be
    # distinguishable: opportunityCount==0 alone does not imply ERROR,
    # but a dead task always does, regardless of opportunity count.
    assert status["opportunityCount"] == 0
    assert status["collectors"]["orbit"]["collectorStatus"] == "ERROR"
    # The other two collectors are unaffected by Orbit's failure.
    assert status["collectors"]["onwin"]["collectorStatus"] in ("RUNNING", "STARTING")
    assert status["collectors"]["betkanyon"]["collectorStatus"] in ("RUNNING", "STARTING")


@pytest.mark.anyio
async def test_status_file_missing_defaults_to_stopped_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, "STATUS_FILE", tmp_path / "does_not_exist.json")

    status = collector.get_collector_status()

    assert status["collectors"]["orbit"]["collectorStatus"] == "STOPPED"
    assert status["opportunityCount"] == 0
