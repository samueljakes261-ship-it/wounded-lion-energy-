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
from kenyan.log import log_arb
from kenyan.opportunity_store import KenyanOpportunityStore
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

    Prematch catalogues are large enough that matching on the HTTP
    request path times out and the UI shows an empty list. A background
    thread refreshes the caches; GET /kenyan/opportunities only reads.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._workers: Dict[str, BaseKenyanWorker] = {}
        self._live_engine = KenyanArbitrageEngine()
        self._prematch_engine = KenyanArbitrageEngine()
        self._live_store = KenyanOpportunityStore()
        self._prematch_store = KenyanOpportunityStore()
        self._started = False
        self._started_at = None
        self._live_compute_lock = threading.Lock()
        self._prematch_compute_lock = threading.Lock()
        self._live_cache = ([], 0.0)
        self._prematch_cache = ([], 0.0)
        self._compute_stop = threading.Event()
        self._compute_thread = None

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

            self._compute_stop.clear()
            self._compute_thread = threading.Thread(
                target=self._compute_loop,
                name="kenyan-compute",
                daemon=True,
            )
            self._compute_thread.start()

            self._started = True
            self._started_at = time.time()

    def stop(self):
        self._compute_stop.set()
        thread = self._compute_thread
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._started = False
            self._compute_thread = None
        if thread is not None:
            thread.join(timeout=8)
        for worker in workers:
            worker.stop()

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

    def _store_cache(self, lock, cache_attr, result):
        with lock:
            setattr(self, cache_attr, (result, time.time()))

    def _read_cache(self, lock, cache_attr):
        with lock:
            cached, _stamped = getattr(self, cache_attr)
            return cached

    def _refresh_opportunities(self, status, engine, store, lock, cache_attr):
        try:
            computed = engine.compute_opportunities(self._matches_for(status))
            result = store.apply(computed)
        except Exception as exc:  # noqa: BLE001
            log_arb(
                event=status,
                market="ALL",
                decision="REJECT",
                reason=f"COMPUTE_ERROR:{type(exc).__name__}",
            )
            return
        self._store_cache(lock, cache_attr, result)

    def _compute_loop(self):
        while not self._compute_stop.is_set():
            self._refresh_opportunities(
                LIVE,
                self._live_engine,
                self._live_store,
                self._live_compute_lock,
                "_live_cache",
            )
            if self._compute_stop.is_set():
                break
            self._refresh_opportunities(
                PREMATCH,
                self._prematch_engine,
                self._prematch_store,
                self._prematch_compute_lock,
                "_prematch_cache",
            )
            self._compute_stop.wait(1.0)

    def get_live_opportunities(self):
        return self._read_cache(self._live_compute_lock, "_live_cache")

    def get_prematch_opportunities(self):
        return self._read_cache(self._prematch_compute_lock, "_prematch_cache")

    def get_worker_statuses(self) -> Dict[str, dict]:
        with self._lock:
            workers = dict(self._workers)

        return {name: worker.get_status() for name, worker in workers.items()}

    def get_engine_status(self) -> dict:
        with self._lock:
            started = self._started
            started_at = self._started_at

        worker_statuses = self.get_worker_statuses()
        live_cached, _live_stamped = self._live_cache
        prematch_cached, _prematch_stamped = self._prematch_cache

        return {
            "started": started,
            "started_at": started_at,
            "workers": worker_statuses,
            "live_opportunity_count": len(live_cached) if started else 0,
            "prematch_opportunity_count": len(prematch_cached) if started else 0,
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
