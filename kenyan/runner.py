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

from kenyan.config import (
    KENYAN_LIVE_COMPUTE_IDLE_SECONDS,
    KENYAN_LIVE_OPPORTUNITY_RETENTION_SECONDS,
    KENYAN_PREMATCH_OPPORTUNITY_RETENTION_SECONDS,
    LIVE,
    PREMATCH,
)
from kenyan.engine import KenyanArbitrageEngine
from kenyan.log import log_arb
from kenyan.metrics import log_cycle
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
        self._live_store = KenyanOpportunityStore(
            retention_seconds=KENYAN_LIVE_OPPORTUNITY_RETENTION_SECONDS
        )
        self._prematch_store = KenyanOpportunityStore(
            retention_seconds=KENYAN_PREMATCH_OPPORTUNITY_RETENTION_SECONDS
        )
        self._started = False
        self._started_at = None
        self._live_compute_lock = threading.Lock()
        self._prematch_compute_lock = threading.Lock()
        self._live_cache = ([], 0.0)
        self._prematch_cache = ([], 0.0)
        self._compute_stop = threading.Event()
        self._live_compute_thread = None
        self._prematch_compute_thread = None
        self._live_compute_seq = 0
        self._prematch_compute_seq = 0
        self._live_applied_seq = 0
        self._prematch_applied_seq = 0
        self._live_ready = threading.Event()
        self._live_last_fingerprint = None
        self._live_last_computed = None
        self._live_cycle_id = 0
        self._live_last_process = {}

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

            for name, worker in self._workers.items():
                if name.endswith("_live"):
                    worker.set_on_snapshot(self._notify_live_ready)
                worker.start()

            self._compute_stop.clear()
            self._live_compute_thread = threading.Thread(
                target=self._compute_loop_live,
                name="kenyan-compute-live",
                daemon=True,
            )
            self._prematch_compute_thread = threading.Thread(
                target=self._compute_loop_prematch,
                name="kenyan-compute-prematch",
                daemon=True,
            )
            self._live_compute_thread.start()
            self._prematch_compute_thread.start()

            self._started = True
            self._started_at = time.time()

    def stop(self):
        self._compute_stop.set()
        self._live_ready.set()
        live_thread = self._live_compute_thread
        prematch_thread = self._prematch_compute_thread
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._started = False
            self._live_compute_thread = None
            self._prematch_compute_thread = None
        for thread in (live_thread, prematch_thread):
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

    def _read_cache(self, lock, cache_attr):
        with lock:
            cached, _stamped = getattr(self, cache_attr)
            return cached

    def _notify_live_ready(self):
        self._live_ready.set()

    def _live_snapshot_fingerprint(self):
        parts = []
        with self._lock:
            workers = [
                worker for name, worker in self._workers.items() if name.endswith("_live")
            ]
        for worker in workers:
            parts.append((worker.name, worker.content_fingerprint(), worker.snapshot_meta()["acquired_seq"]))
        return tuple(parts)

    def _refresh_live_opportunities(self):
        gather_started = time.monotonic()
        matches = self._matches_for(LIVE)
        gather_ms = (time.monotonic() - gather_started) * 1000
        fingerprint = self._live_snapshot_fingerprint()
        price_ages = []
        confirm_ages = []
        now = time.time()
        for match in matches:
            collected = getattr(match, "collected_at", None)
            confirmed = getattr(match, "confirmed_at", None)
            if collected is not None:
                try:
                    price_ages.append(max(0.0, now - collected.timestamp()))
                except Exception:
                    pass
            if confirmed is not None:
                try:
                    confirm_ages.append(max(0.0, now - confirmed.timestamp()))
                except Exception:
                    pass
        snapshot_age = max(price_ages) if price_ages else 0.0
        confirm_age = max(confirm_ages) if confirm_ages else 0.0

        with self._live_compute_lock:
            self._live_compute_seq += 1
            seq = self._live_compute_seq
            self._live_cycle_id += 1
            cycle_id = self._live_cycle_id

        skipped = fingerprint == self._live_last_fingerprint and self._live_last_computed is not None
        compute_started = time.monotonic()
        try:
            if skipped:
                computed = self._live_last_computed
            else:
                computed = self._live_engine.compute_opportunities(matches)
                self._live_last_computed = computed
                self._live_last_fingerprint = fingerprint
            result = self._live_store.apply(computed)
        except Exception as exc:  # noqa: BLE001
            log_arb(
                event=LIVE,
                market="ALL",
                decision="REJECT",
                reason=f"COMPUTE_ERROR:{type(exc).__name__}",
            )
            return
        compute_ms = (time.monotonic() - compute_started) * 1000
        process_ms = (time.monotonic() - gather_started) * 1000

        with self._live_compute_lock:
            if seq < self._live_applied_seq:
                return
            self._live_applied_seq = seq
            self._live_cache = (result, time.time())
            self._live_last_process = {
                "cycle_id": cycle_id,
                "gather_ms": round(gather_ms, 2),
                "compute_ms": round(compute_ms, 2),
                "process_ms": round(process_ms, 2),
                "skipped_unchanged": skipped,
                "snapshot_age_seconds": round(snapshot_age, 2),
                "confirm_age_seconds": round(confirm_age, 2),
                "match_count": len(matches),
                "computed": len(computed),
                "retained": len(result),
                "eligible_bookmakers": len({getattr(m, "bookmaker", "") for m in matches}),
            }
        log_cycle(
            mode=LIVE,
            cycle_id=cycle_id,
            stage="process",
            gather_ms=round(gather_ms, 2),
            compute_ms=round(compute_ms, 2),
            process_ms=round(process_ms, 2),
            skipped_unchanged=int(skipped),
            snapshot_age_seconds=round(snapshot_age, 2),
            confirm_age_seconds=round(confirm_age, 2),
            matches=len(matches),
            computed=len(computed),
            retained=len(result),
            compute_seq=seq,
        )

    def _refresh_opportunities(
        self,
        status,
        engine,
        store,
        lock,
        cache_attr,
        seq_attr,
        applied_attr,
    ):
        with lock:
            seq = getattr(self, seq_attr) + 1
            setattr(self, seq_attr, seq)
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
        with lock:
            if seq < getattr(self, applied_attr):
                return
            setattr(self, applied_attr, seq)
            setattr(self, cache_attr, (result, time.time()))
        log_cycle(
            mode=status,
            computed=len(computed),
            retained=len(result),
            compute_seq=seq,
        )

    def _compute_loop_live(self):
        while not self._compute_stop.is_set():
            self._refresh_live_opportunities()
            if self._compute_stop.is_set():
                break
            self._live_ready.wait(timeout=KENYAN_LIVE_COMPUTE_IDLE_SECONDS)
            self._live_ready.clear()
            if self._compute_stop.is_set():
                break

    def _compute_loop_prematch(self):
        while not self._compute_stop.is_set():
            self._refresh_opportunities(
                PREMATCH,
                self._prematch_engine,
                self._prematch_store,
                self._prematch_compute_lock,
                "_prematch_cache",
                "_prematch_compute_seq",
                "_prematch_applied_seq",
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
            "live_pipeline": dict(self._live_last_process),
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
