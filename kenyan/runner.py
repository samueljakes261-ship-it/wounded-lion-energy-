"""
Kenyan bookmakers orchestrator.

Owns the 8 persistent workers (4 bookmakers x LIVE/PREMATCH), started
ONCE and reused for the lifetime of the process -- never recreated per
request/tick, matching the existing project's own pattern for
OnWin/BetKanyon (see collector.py's `start_workers()` /
`_get_onwin_handle()` / `_get_betkanyon_worker()`, which this module
does not import from or otherwise touch).

This is the single integration point used by:
  - run_kenyan_engine.py (the new Kenyan-only startup command)
  - kenyan/api_router.py (the isolated Kenyan FastAPI routes)
"""
import threading
import time
from typing import Dict, List

from kenyan.config import LIVE, PREMATCH
from kenyan.engine import KenyanArbitrageEngine
from kenyan.workers import bet22, betika, onexbet, sportpesa
from kenyan.workers.base import BaseKenyanWorker

_WORKER_BUILDERS = {
    "SportPesa": (sportpesa.build_live_worker, sportpesa.build_prematch_worker),
    "Betika": (betika.build_live_worker, betika.build_prematch_worker),
    "1xBet": (onexbet.build_live_worker, onexbet.build_prematch_worker),
    "22Bet": (bet22.build_live_worker, bet22.build_prematch_worker),
}


class KenyanEngineRunner:
    """
    Starts/stops the 4 Kenyan bookmakers' LIVE + PREMATCH workers and
    exposes their combined, freshly-matched arbitrage opportunities
    and per-worker health.

    KENYAN LIVE and KENYAN PREMATCH opportunities are computed and
    returned SEPARATELY (two independent engine runs) so they can
    never be mixed into one combined list, per the task's explicit
    requirement.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._workers: Dict[str, BaseKenyanWorker] = {}
        self._live_engine = KenyanArbitrageEngine()
        self._prematch_engine = KenyanArbitrageEngine()
        self._started = False
        self._started_at = None

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------

    def start(self):
        with self._lock:
            if self._started:
                return

            for bookmaker, (build_live, build_prematch) in _WORKER_BUILDERS.items():
                live_worker = build_live()
                prematch_worker = build_prematch()
                self._workers[f"{bookmaker}_live"] = live_worker
                self._workers[f"{bookmaker}_prematch"] = prematch_worker

            for worker in self._workers.values():
                worker.start()

            self._started = True
            self._started_at = time.time()

    def stop(self):
        with self._lock:
            for worker in self._workers.values():
                worker.stop()
            self._workers.clear()
            self._started = False

    def is_started(self) -> bool:
        with self._lock:
            return self._started

    # ------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------

    def _matches_for(self, status: str) -> List:
        matches = []
        suffix = "_live" if status == LIVE else "_prematch"

        with self._lock:
            workers = [
                worker for name, worker in self._workers.items() if name.endswith(suffix)
            ]

        for worker in workers:
            matches.extend(worker.get_matches())

        return matches

    def get_live_opportunities(self):
        return self._live_engine.compute_opportunities(self._matches_for(LIVE))

    def get_prematch_opportunities(self):
        return self._prematch_engine.compute_opportunities(self._matches_for(PREMATCH))

    def get_worker_statuses(self) -> Dict[str, dict]:
        with self._lock:
            workers = dict(self._workers)

        return {name: worker.get_status() for name, worker in workers.items()}

    def get_engine_status(self) -> dict:
        with self._lock:
            started = self._started
            started_at = self._started_at

        worker_statuses = self.get_worker_statuses()

        return {
            "started": started,
            "started_at": started_at,
            "workers": worker_statuses,
            "live_opportunity_count": len(self.get_live_opportunities()) if started else 0,
            "prematch_opportunity_count": (
                len(self.get_prematch_opportunities()) if started else 0
            ),
        }


# Single, lazily-created, process-lifetime instance -- mirrors
# collector.py's own "create once, reuse forever" handles for
# OnWin/BetKanyon, but entirely independent of them.
_runner: KenyanEngineRunner = None
_runner_lock = threading.Lock()


def get_runner() -> KenyanEngineRunner:
    global _runner

    with _runner_lock:
        if _runner is None:
            _runner = KenyanEngineRunner()

    return _runner


def start_kenyan_workers():
    get_runner().start()


def stop_kenyan_workers():
    get_runner().stop()
