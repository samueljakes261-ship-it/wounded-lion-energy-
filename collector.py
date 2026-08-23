import asyncio
import json
import multiprocessing
import os
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from debug import odds_trace
from engine.collector_health import (
    DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    INPLACE_RETRY_PAUSE_SECONDS,
    MAX_INPLACE_RETRIES,
    RECOVER_AFTER_CONSECUTIVE_SUCCESSES,
    is_connection_dead_error,
)
from engine.match_finder import MatchFinder
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator
from engine.back_lay_detector import BackLayDetector
from models.arbitrage_opportunity import ArbitrageOpportunity

from parsers.betkanyon.worker import BetkanyonWorker
from parsers.betkanyon_prematch.worker import BetkanyonPrematchWorker
from parsers.onwin.feed import OnwinFeed
from parsers.onwin_prematch.worker import OnwinPrematchWorker
from parsers.orbit.worker import OrbitWorker
from parsers.orbit_prematch.worker import OrbitPrematchWorker
from engine.recovery import (
    display_collector_status,
    scheduled_restart_active,
    should_replace_snapshot,
)
from parsers.kolay90_prematch.worker import Kolay90PrematchWorker
from prematch.mode import engine_mode_label, is_prematch_only
from prematch.pipeline import (
    PREMATCH_CACHE_FILE,
    PREMATCH_MAX_ODDS_AGE_SECONDS,
    build_prematch_opportunities,
    serialize_prematch_cache,
    _filter_stale as _filter_prematch_stale,
)
from prematch.back_lay import find_prematch_back_lay


CACHE_FILE = Path("cached_opportunities.json")

# Collector/engine health, written every tick so a SEPARATE process
# (api.py) can report live collector status without importing/starting
# its own copy of the OnWin/BetKanyon/Orbit workers -- see
# get_collector_status() and api.py's /status endpoint. Same
# cross-process pattern as CACHE_FILE above.
STATUS_FILE = Path("cached_status.json")


def _atomic_write_text(path: Path, text: str) -> None:
    """
    Write `text` to `path` via a same-directory temp file + replace.

    Direct write_text() on Windows can raise OSError 22 (Invalid
    argument) or a sharing violation when another process (api.py)
    is reading the same file at the same moment. replace() is atomic
    on the same volume, so readers always see a complete file.
    """
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)

# OnWin reconnect backoff: mirrors parsers/betkanyon/worker.py's and
# parsers/orbit/worker.py's INITIAL_BACKOFF_SECONDS/MAX_BACKOFF_SECONDS
# module constants (rather than a literal inline in
# _onwin_worker_main) so tests can override them, and so the value is
# documented in exactly one place.
ONWIN_INITIAL_BACKOFF_SECONDS = 5
ONWIN_MAX_BACKOFF_SECONDS = 60


# ============================================================
# FRESHNESS / TIMING CONFIGURATION
#
# Configurable via env vars rather than hard-coded in multiple
# places, per the project's own guidance.
# ============================================================

# An odds snapshot older than this is treated as dead and excluded
# from arbitrage calculations rather than silently reused as "live".
#
# Rationale for the default (30s): BetKanyon's own worker polls roughly
# every BETKANYON_POLL_INTERVAL (~3s by default) and OnWin's update
# feed pushes continuously but irregularly. 30s is several multiples of
# BetKanyon's normal cycle time and comfortably longer than any normal
# quiet period on either feed, so brief network jitter or a quiet
# stretch with no odds changes doesn't trip it, while a genuinely dead
# feed still gets caught well before staleness would go unnoticed.
MAX_ODDS_AGE_SECONDS = float(os.getenv("MAX_ODDS_AGE_SECONDS", "30"))

# An early, non-exclusionary warning threshold -- "this is taking
# unusually long" rather than "this data is now considered dead".
WARN_ODDS_AGE_SECONDS = min(15.0, MAX_ODDS_AGE_SECONDS / 2)

# How often the engine recomputes matching/arbitrage from whatever
# OnWin/BetKanyon snapshots are currently available.
#
# Rationale: the tick itself does no network/browser work -- it only
# reads already-published in-memory state and reruns the existing
# (cheap) MatchFinder/BestOddsSelector/ArbitrageDetector pipeline over
# at most a few hundred MatchOdds. Ticking at ~1s keeps the delay
# between "a bookmaker publishes fresh odds" and "the engine has
# reacted" low without turning this into a busy loop.
ENGINE_TICK_SECONDS = float(os.getenv("ENGINE_TICK_SECONDS", "1"))

# How often to print a heartbeat when nothing new has actually
# happened, so the terminal stays readable instead of repeating
# "no arb" every tick.
HEARTBEAT_INTERVAL_SECONDS = 5.0

# Minimum spacing between repeated staleness warnings for the same
# bookmaker, so a feed that's stuck stale doesn't spam the terminal.
STALE_WARNING_REPEAT_SECONDS = 15.0


# ============================================================
# COLLECTOR HEALTH STATUS
#
# DATA COLLECTION IS NOT THE SAME THING AS "AN ARBITRAGE OPPORTUNITY
# CURRENTLY EXISTS". A collector reporting RUNNING with 0 current
# opportunities is completely healthy; opportunities==0 must never be
# interpreted as "the collector stopped". This enum/classifier is the
# single place that decides collector health, computed purely from
# each worker's OWN connection/publish state (never from whether the
# arbitrage engine found anything) -- see _classify_collector_status().
# ============================================================

class CollectorStatus(str, Enum):
    RUNNING = "RUNNING"
    STARTING = "STARTING"
    RECOVERING = "RECOVERING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


def _classify_collector_status(
    raw_status: str | None,
    age,
    alive: bool,
    consecutive_failures: int = 0,
    consecutive_successes: int = 0,
    reconnect_count: int = 0,
    max_age=None,
) -> str:
    """
    Maps one worker's own internal state onto the collector health
    enum:

      - raw_status: "starting" / "connecting" / "running" /
        "reconnecting" / "stopped" -- the worker's own low-level state
        word.
      - age: seconds since the worker's last successful publish
        (None if it has never published).
      - alive: whether its process/thread/task is still alive.
      - consecutive_failures / consecutive_successes: how many
        acquisition cycles in a row have just failed/succeeded (see
        engine.collector_health) -- this is what gives the mapping
        HYSTERESIS instead of reacting to a single blip.
      - reconnect_count: how many times this worker has ever had to
        fully reconnect -- used only to decide whether a short
        RECOVERING window (as opposed to jumping straight back to
        RUNNING) is meaningful right after a recovery.

    Deliberately takes NO opportunity/arbitrage information as input --
    that is the whole point (see module docstring above).

    HYSTERESIS (see engine/collector_health.py for the chosen
    thresholds and rationale): a single failed cycle -- even one that
    forces the worker to start reconnecting -- must NOT immediately
    read as DEGRADED as long as (a) the last-known-good data is still
    within MAX_ODDS_AGE_SECONDS, the same bar collector.py itself uses
    to decide whether that data may still feed the arbitrage engine,
    and (b) failures haven't piled up enough in a row to look like a
    sustained problem rather than a blip. This directly implements the
    "single timeout -> retry -> success -> RUNNING, NOT single timeout
    -> DEGRADED -> opportunities disappear" requirement: DEGRADED here
    tracks whether the DATA is trustworthy, not whether a reconnect
    happens to be in flight at this exact instant.
    """

    if not alive:
        return (
            CollectorStatus.STOPPED.value
            if raw_status == "stopped"
            else CollectorStatus.ERROR.value
        )

    if raw_status == "stopped":
        return CollectorStatus.STOPPED.value

    if raw_status == "starting":
        return CollectorStatus.STARTING.value

    # Data-safety floor: no amount of hysteresis can hide genuinely
    # stale data -- this check is unconditional and always wins,
    # regardless of raw_status or failure/success counts.
    stale_after = MAX_ODDS_AGE_SECONDS if max_age is None else max_age
    if age is not None and age > stale_after:
        return CollectorStatus.DEGRADED.value

    # Sustained-failure floor: enough CONSECUTIVE failures in a row is
    # a real, meaningful problem regardless of raw_status wording or
    # how fresh the last-known-good data still happens to be (a worker
    # that keeps failing to reconnect will eventually also fail this
    # age check above, but this catches it sooner and doesn't rely on
    # timing alone).
    if consecutive_failures >= DEGRADE_AFTER_CONSECUTIVE_FAILURES:
        return CollectorStatus.DEGRADED.value

    if age is None:
        # Alive, not stopped/starting-labeled, never published, and
        # not yet failing persistently -- still coming up.
        return CollectorStatus.STARTING.value

    # From here: age is fresh (<= MAX_ODDS_AGE_SECONDS) AND failures
    # are below the DEGRADED threshold, i.e. the data is genuinely
    # USABLE right now. The only remaining question is how confidently
    # "back to normal" this worker looks: if it has reconnected at
    # least once and hasn't yet strung together
    # RECOVER_AFTER_CONSECUTIVE_SUCCESSES clean cycles since, report
    # RECOVERING rather than jumping straight back to full RUNNING
    # confidence on the very first successful retry.
    if reconnect_count > 0 and consecutive_successes < RECOVER_AFTER_CONSECUTIVE_SUCCESSES:
        return CollectorStatus.RECOVERING.value

    return CollectorStatus.RUNNING.value


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ============================================================
# ONWIN WORKER
# ============================================================
#
# OnWin uses Playwright Sync API, so it must run in a completely
# separate process from the asyncio engine.
#
# IMPORTANT: unlike a normal "collect once and exit" worker, this
# worker is LONG-LIVED. It opens the ZenRows browser/session and
# navigates to OnWin exactly ONCE, captures get_main_line.erisgaming
# ONCE to build local state, and then stays connected, continuously
# patching state from find_event_snapshots.erisgaming responses for as
# long as the process runs. It is started once (lazily, on first use)
# and reused by every collection cycle -- it is never recreated on a
# per-cycle basis.
#
# Do NOT move this function inside a class/closure. Windows
# multiprocessing (spawn) requires the target to be a plain
# module-level function so it can be pickled/re-imported in the child
# process.
# ============================================================

def _configure_onwin_child_stdio():
    """
    Windows spawn children are started WITHOUT python -u, so print()
    is fully buffered when stdout is a pipe and OnWin logs never
    appear in the engine terminal. Line-buffer, and also tee into
    runtime/onwin_worker.log so the parent can diagnose a hung child
    even when console inheritance fails. Never writes secrets: this
    worker already only prints type names and counts.
    """
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    if multiprocessing.parent_process() is None:
        return

    try:
        log_dir = Path("runtime")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(
            log_dir / "onwin_worker.log",
            "a",
            encoding="utf-8",
            buffering=1,
        )
    except OSError:
        return

    class _Tee:
        def __init__(self, *streams):
            self._streams = streams

        def write(self, data):
            for stream in self._streams:
                try:
                    stream.write(data)
                    stream.flush()
                except Exception:
                    pass

        def flush(self):
            for stream in self._streams:
                try:
                    stream.flush()
                except Exception:
                    pass

    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)


def _onwin_worker_main(shared_state, stop_event):
    """
    Runs in its own process for the lifetime of the engine.

    shared_state (a multiprocessing.Manager dict) is how the collector
    reads the latest OnWin MatchOdds without any per-cycle browser
    activity: this worker publishes into it, the collector only reads
    from it.
    """

    _configure_onwin_child_stdio()

    feed = None
    backoff_seconds = ONWIN_INITIAL_BACKOFF_SECONDS
    first_connect = True

    def touch():
        # "We successfully heard from the feed just now" -- distinct
        # from publish() below. A quiet market whose 1X2 price simply
        # hasn't changed in a while is still fresh, healthy data, NOT
        # stale data, as long as find_event_snapshots keeps arriving.
        # last_update_at therefore tracks feed *liveness*, not "value
        # last changed", so the staleness guard in collect_opportunities
        # doesn't punish a healthy-but-quiet feed.
        shared_state["last_update_at"] = time.time()
        shared_state["status"] = "running"
        shared_state["error"] = None

    def publish(_changed_event_ids=None):
        try:
            shared_state["matches"] = feed.state.get_match_odds()
            shared_state["event_count"] = feed.state.event_count
            touch()
        except Exception as exc:
            shared_state["error"] = f"{type(exc).__name__}: {exc}"

    def progress(phase):
        shared_state["phase"] = phase
        shared_state["last_attempt_at"] = time.time()

    def log_update(version, event_count, changed_count):
        # Called for EVERY processed find_event_snapshots response
        # (not just ones that changed something), so this doubles as
        # the feed's liveness signal.
        shared_state["phase"] = "running"
        touch()

        # This is the one place that could flood the terminal on a
        # very chatty feed -- kept to one short line per response, per
        # the project's own visibility spec.
        ts = time.strftime("%H:%M:%S")

        if changed_count:
            print(
                f"[ONWIN] {ts} | update v={version} | "
                f"events={event_count} | changed_1x2={changed_count}"
            )
        else:
            print(f"[ONWIN] {ts} | update v={version} | no relevant odds change")

    while not stop_event.is_set():

        shared_state["last_attempt_at"] = time.time()
        shared_state["request_count"] = shared_state.get("request_count", 0) + 1

        try:
            if feed is None or not feed.is_alive():

                if feed is not None:
                    try:
                        feed.close()
                    except Exception:
                        pass

                shared_state["status"] = "connecting"

                if first_connect:
                    print("[ONWIN] Starting persistent browser...")
                    first_connect = False
                else:
                    shared_state["reconnect_count"] = (
                        shared_state.get("reconnect_count", 0) + 1
                    )
                    print("[ONWIN] Reconnecting: creating a new browser/session...")

                feed = OnwinFeed()
                feed.start(
                    on_change=publish,
                    on_update=log_update,
                    on_progress=progress,
                )

                shared_state["phase"] = "running"
                publish()

                print(
                    "[ONWIN] Initial snapshot received | "
                    f"State loaded: {feed.state.event_count} football events "
                    f"tracked / {len(feed.state.get_match_odds())} live"
                )
                print("[ONWIN] Continuous update feed active")

                # A successful (re)connect resets the backoff so a
                # single blip doesn't leave us waiting a full minute
                # between later, unrelated reconnect attempts.
                backoff_seconds = ONWIN_INITIAL_BACKOFF_SECONDS

            # Pumps the browser's message loop so queued
            # find_event_snapshots responses are actually delivered to
            # the update handler. Does not navigate or fetch anything.
            feed.poll(tick_ms=500)

            # A full poll cycle completed without raising. This alone
            # is what resets the consecutive-failure hysteresis (see
            # engine/collector_health.py) -- individual
            # find_event_snapshots responses have their own internal
            # try/except in OnwinFeed and never propagate here, so
            # reaching this line means the browser's message loop
            # itself is genuinely still alive and responsive.
            shared_state["consecutive_failures"] = 0
            shared_state["consecutive_successes"] = (
                shared_state.get("consecutive_successes", 0) + 1
            )
            shared_state["success_count"] = shared_state.get("success_count", 0) + 1

            # Push-feed liveness: poll() succeeding only proves the
            # Playwright page is still open, NOT that OnWin is still
            # sending find_event_snapshots. If the update stream goes
            # silent past the same staleness bar the engine uses,
            # reconnect -- otherwise this worker stays "running" with
            # frozen odds while the engine correctly excludes them.
            silent_for = None
            seconds_since = getattr(feed, "seconds_since_last_update", None)
            if callable(seconds_since):
                silent_for = seconds_since()
            if silent_for is not None and silent_for > MAX_ODDS_AGE_SECONDS:
                raise TimeoutError(
                    f"OnWin update feed silent for {silent_for:.0f}s"
                )

        except Exception as exc:
            shared_state["failed_count"] = shared_state.get("failed_count", 0) + 1
            shared_state["consecutive_successes"] = 0
            consecutive_failures = shared_state.get("consecutive_failures", 0) + 1
            shared_state["consecutive_failures"] = consecutive_failures
            shared_state["error"] = f"{type(exc).__name__}: {exc}"

            # LEVEL 1/2 escalation (see engine/collector_health.py):
            # only tear down and recreate the ENTIRE browser session
            # when this specific failure looks like the page/context/
            # browser is actually gone, or after enough consecutive
            # failures on the SAME session that retrying it further is
            # no longer worth it. Everything else is treated as a
            # local, retryable blip -- the existing feed/page is kept
            # exactly as-is and the same poll() is simply tried again
            # shortly after, without paying the cost (and the
            # opportunity-visibility risk -- see MAX_ODDS_AGE_SECONDS)
            # of a full ZenRows browser re-navigation for something
            # that may well resolve itself on the very next tick.
            if is_connection_dead_error(exc) or consecutive_failures >= MAX_INPLACE_RETRIES:
                shared_state["status"] = "reconnecting"

                print(
                    f"[ONWIN] Cycle failed ({type(exc).__name__}: {exc}). "
                    f"Reconnecting in {backoff_seconds}s..."
                )

                if feed is not None:
                    try:
                        feed.close()
                    except Exception:
                        pass
                    feed = None

                time.sleep(min(backoff_seconds, ONWIN_MAX_BACKOFF_SECONDS))
                backoff_seconds = min(backoff_seconds * 2, ONWIN_MAX_BACKOFF_SECONDS)
            else:
                print(
                    f"[ONWIN] Transient error ({type(exc).__name__}: {exc}), "
                    f"retrying in place ({consecutive_failures}/{MAX_INPLACE_RETRIES})..."
                )
                time.sleep(INPLACE_RETRY_PAUSE_SECONDS)

    if feed is not None:
        try:
            feed.close()
        except Exception:
            pass


class OnwinWorkerHandle:
    """
    Owns exactly ONE persistent OnWin acquisition process.

    Created lazily on first use (see _get_onwin_handle) and reused by
    every subsequent collection cycle: the browser/session inside the
    worker process is opened once and never recreated per cycle.
    """

    def __init__(self):
        self._ctx = multiprocessing.get_context("spawn")
        self._manager = self._ctx.Manager()

        self.shared_state = self._manager.dict()
        self.shared_state["matches"] = []
        self.shared_state["event_count"] = 0
        self.shared_state["status"] = "starting"
        self.shared_state["phase"] = "starting"
        self.shared_state["error"] = None
        self.shared_state["last_update_at"] = None
        self.shared_state["last_attempt_at"] = None
        self.shared_state["consecutive_failures"] = 0
        self.shared_state["consecutive_successes"] = 0
        self.shared_state["reconnect_count"] = 0
        self.shared_state["request_count"] = 0
        self.shared_state["success_count"] = 0
        self.shared_state["failed_count"] = 0

        self._stop_event = self._ctx.Event()

        self._process = self._ctx.Process(
            target=_onwin_worker_main,
            args=(self.shared_state, self._stop_event),
            daemon=True,
        )

        self._process.start()

    def get_matches(self):
        """
        Returns the most recently published OnWin MatchOdds list.

        This is a cheap read of a small in-memory structure (never a
        multi-megabyte payload) -- no browser activity, no network
        call, no new process.
        """

        if not self._process.is_alive():
            return []

        return list(self.shared_state.get("matches", []))

    def status(self):
        return dict(self.shared_state)

    def stop(self, timeout=10):
        self._stop_event.set()
        self._process.join(timeout=timeout)

        if self._process.is_alive():
            self._process.terminate()

        self._manager.shutdown()


_onwin_handle: OnwinWorkerHandle | None = None


def _get_onwin_handle() -> OnwinWorkerHandle:
    """
    Lazily creates the single persistent OnWin worker on first use,
    then always returns that same instance.
    """

    global _onwin_handle

    if _onwin_handle is None:
        _onwin_handle = OnwinWorkerHandle()

    return _onwin_handle


def stop_onwin_worker():
    """
    Stop the persistent OnWin worker, if one is running.

    Not required for normal operation (the worker is a daemon process
    and the engine typically runs until the process is killed), but
    useful for tests and for a clean shutdown path.
    """

    global _onwin_handle

    if _onwin_handle is not None:
        _onwin_handle.stop()
        _onwin_handle = None


# ============================================================
# BETKANYON WORKER
# ============================================================
#
# BetKanyon does not need a separate process the way OnWin does: its
# acquisition is a simple pull (fetch -> decrypt -> parse -> adapt) on
# an already-open, already-authenticated page rather than a continuous
# Playwright event-listener stream. A background thread is sufficient
# and keeps things simpler (direct shared memory + a lock instead of a
# multiprocessing.Manager). See parsers/betkanyon/worker.py for the
# reasoning and the poll loop itself.
#
# Same rule as OnWin: created lazily ONCE and reused by every
# collection cycle -- never recreated per cycle.
# ============================================================

_betkanyon_worker: BetkanyonWorker | None = None


def _get_betkanyon_worker() -> BetkanyonWorker:
    global _betkanyon_worker

    if _betkanyon_worker is None:
        _betkanyon_worker = BetkanyonWorker()
        _betkanyon_worker.start()

    return _betkanyon_worker


def stop_betkanyon_worker():
    """Stop the persistent BetKanyon worker, if one is running (used
    by tests/shutdown)."""

    global _betkanyon_worker

    if _betkanyon_worker is not None:
        _betkanyon_worker.stop()
        _betkanyon_worker = None


# ============================================================
# ORBIT WORKER
# ============================================================
#
# Orbit needs no browser at all: a REST call for the market catalogue,
# then one persistent SockJS/WebSocket connection that pushes price
# updates continuously and independently per market -- genuinely
# event-driven, unlike BetKanyon's fixed-interval poll. Because the
# underlying client (websockets) is asyncio-native, OrbitWorker runs
# as a plain asyncio.Task on the SAME event loop as this engine's main
# loop instead of a separate thread/process. See
# parsers/orbit/worker.py.
#
# Same rule as OnWin/BetKanyon: created lazily ONCE and reused by
# every collection cycle -- never recreated per cycle.
# ============================================================

_orbit_worker: OrbitWorker | None = None


def _get_orbit_worker() -> OrbitWorker:
    global _orbit_worker

    if _orbit_worker is None:
        _orbit_worker = OrbitWorker()
        _orbit_worker.start()

    return _orbit_worker


async def stop_orbit_worker():
    """Stop the persistent Orbit worker, if one is running (used by
    tests/shutdown)."""

    global _orbit_worker

    if _orbit_worker is not None:
        await _orbit_worker.stop()
        _orbit_worker = None


# ============================================================
# PREMATCH WORKERS (additive; live workers above are unchanged)
# ============================================================

_betkanyon_prematch_worker: BetkanyonPrematchWorker | None = None
_orbit_prematch_worker: OrbitPrematchWorker | None = None
_onwin_prematch_worker: OnwinPrematchWorker | None = None
_kolay90_prematch_worker: Kolay90PrematchWorker | None = None
_prematch_last_matched = 0
_prematch_last_opportunities = 0
_prematch_last_back_lay = 0
_prematch_last_cache_n = 0
_prematch_back_lay_sig = None


def _get_betkanyon_prematch_worker() -> BetkanyonPrematchWorker:
    global _betkanyon_prematch_worker
    if _betkanyon_prematch_worker is None:
        _betkanyon_prematch_worker = BetkanyonPrematchWorker()
        _betkanyon_prematch_worker.start()
    return _betkanyon_prematch_worker


def _get_orbit_prematch_worker() -> OrbitPrematchWorker:
    global _orbit_prematch_worker
    if _orbit_prematch_worker is None:
        _orbit_prematch_worker = OrbitPrematchWorker()
        _orbit_prematch_worker.start()
    return _orbit_prematch_worker


def _get_onwin_prematch_worker() -> OnwinPrematchWorker:
    global _onwin_prematch_worker
    if _onwin_prematch_worker is None:
        _onwin_prematch_worker = OnwinPrematchWorker()
        _onwin_prematch_worker.start()
    return _onwin_prematch_worker


def stop_betkanyon_prematch_worker():
    global _betkanyon_prematch_worker
    if _betkanyon_prematch_worker is not None:
        _betkanyon_prematch_worker.stop()
        _betkanyon_prematch_worker = None


async def stop_orbit_prematch_worker():
    global _orbit_prematch_worker
    if _orbit_prematch_worker is not None:
        await _orbit_prematch_worker.stop()
        _orbit_prematch_worker = None


def stop_onwin_prematch_worker():
    global _onwin_prematch_worker
    if _onwin_prematch_worker is not None:
        _onwin_prematch_worker.stop()
        _onwin_prematch_worker = None


def _get_kolay90_prematch_worker() -> Kolay90PrematchWorker:
    global _kolay90_prematch_worker
    if _kolay90_prematch_worker is None:
        _kolay90_prematch_worker = Kolay90PrematchWorker()
        _kolay90_prematch_worker.start()
    return _kolay90_prematch_worker


def stop_kolay90_prematch_worker():
    global _kolay90_prematch_worker
    if _kolay90_prematch_worker is not None:
        _kolay90_prematch_worker.stop()
        _kolay90_prematch_worker = None


def start_prematch_workers():
    """Start prematch workers independently of live start_workers()."""
    for name, starter in (
        ("BetKanyon prematch", _get_betkanyon_prematch_worker),
        ("Orbit prematch", _get_orbit_prematch_worker),
        ("OnWin prematch", _get_onwin_prematch_worker),
        ("Kolay90 prematch", _get_kolay90_prematch_worker),
    ):
        try:
            starter()
        except Exception as exc:
            print(
                f"[{name.upper()}] Failed to start worker "
                f"({type(exc).__name__}: {exc}). Other collectors continue."
            )


def start_workers():
    """
    Explicitly start all three persistent bookmaker workers up front so
    they begin acquiring data CONCURRENTLY, rather than each being
    lazily created on first use inside collect_opportunities() (which
    would work the same functionally, but this makes the "all feeds
    start together" intent explicit at startup).

    Each starter is isolated: a failure constructing OnWin must not
    prevent BetKanyon or Orbit from starting, and vice versa.

    Must be called from within a running asyncio event loop (OrbitWorker
    schedules an asyncio.Task) -- see run_engine.py.
    """

    for name, starter in (
        ("OnWin", _get_onwin_handle),
        ("BetKanyon", _get_betkanyon_worker),
        ("Orbit", _get_orbit_worker),
    ):
        try:
            starter()
        except Exception as exc:
            print(
                f"[{name.upper()}] Failed to start worker "
                f"({type(exc).__name__}: {exc}). Other collectors continue."
            )


# Minimum seconds between automatic restarts of the same worker, so a
# process that crashes immediately on start cannot fork-bomb the host.
_WORKER_RESTART_MIN_INTERVAL_SECONDS = 5.0
_worker_restart_at = {
    "onwin": 0.0,
    "betkanyon": 0.0,
    "orbit": 0.0,
    "betkanyon_prematch": 0.0,
    "orbit_prematch": 0.0,
    "onwin_prematch": 0.0,
    "kolay90_prematch": 0.0,
}


async def _restart_worker(name: str, stopper, starter) -> None:
    """
    Tear down a dead worker handle and start a fresh one.

    `stopper` / `starter` are the existing stop_* / _get_* functions
    for that collector so we never create a second parallel worker of
    the same type.
    """

    now = time.time()
    last = _worker_restart_at.get(name, 0.0)
    if now - last < _WORKER_RESTART_MIN_INTERVAL_SECONDS:
        return

    _worker_restart_at[name] = now
    print(f"[{name.upper()}] Worker exited unexpectedly; restarting...")

    try:
        result = stopper()
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        print(
            f"[{name.upper()}] Error while stopping dead worker "
            f"({type(exc).__name__}: {exc})"
        )

    try:
        starter()
    except Exception as exc:
        print(
            f"[{name.upper()}] Restart failed "
            f"({type(exc).__name__}: {exc}). Will retry on a later tick."
        )


async def _ensure_workers_alive():
    """
    Supervisor: if a previously-started worker's process/thread/task
    has died, restart ONLY that worker. The others keep collecting.

    Called once per engine tick so a crash cannot leave a collector
    permanently IDLE/STOPPED with no recovery attempt.
    """

    if _onwin_handle is not None and not _worker_alive(_onwin_handle._process):
        await _restart_worker("onwin", stop_onwin_worker, _get_onwin_handle)

    if _betkanyon_worker is not None and not _worker_alive(_betkanyon_worker._thread):
        await _restart_worker("betkanyon", stop_betkanyon_worker, _get_betkanyon_worker)

    if _orbit_worker is not None and not _worker_alive(_orbit_worker._task):
        await _restart_worker("orbit", stop_orbit_worker, _get_orbit_worker)

    if (
        _betkanyon_prematch_worker is not None
        and not _worker_alive(_betkanyon_prematch_worker._thread)
    ):
        await _restart_worker(
            "betkanyon_prematch",
            stop_betkanyon_prematch_worker,
            _get_betkanyon_prematch_worker,
        )

    if (
        _orbit_prematch_worker is not None
        and not _worker_alive(_orbit_prematch_worker._task)
    ):
        await _restart_worker(
            "orbit_prematch",
            stop_orbit_prematch_worker,
            _get_orbit_prematch_worker,
        )

    if (
        _onwin_prematch_worker is not None
        and not _worker_alive(_onwin_prematch_worker._thread)
    ):
        await _restart_worker(
            "onwin_prematch",
            stop_onwin_prematch_worker,
            _get_onwin_prematch_worker,
        )

    if (
        _kolay90_prematch_worker is not None
        and not _worker_alive(_kolay90_prematch_worker._thread)
    ):
        await _restart_worker(
            "kolay90_prematch",
            stop_kolay90_prematch_worker,
            _get_kolay90_prematch_worker,
        )


# ============================================================
# ENGINE ACTIVITY MONITOR
#
# Small piece of state, persisted across collect_opportunities() calls,
# used only to decide what's worth printing: "fresh data just arrived"
# vs. "just a routine heartbeat" vs. "a feed has gone stale". None of
# this affects the actual matching/arbitrage computation.
# ============================================================

_engine_monitor = {
    "last_onwin_update_at": None,
    "last_betkanyon_update_at": None,
    "last_orbit_update_at": None,
    "last_heartbeat_at": 0.0,
    "last_status_panel_at": 0.0,
    "onwin_last_warn_at": 0.0,
    "betkanyon_last_warn_at": 0.0,
    "orbit_last_warn_at": 0.0,
    "latest_arbitrage": None,
}

# How often the big multi-line status panel (item 12 of the spec) is
# printed. Deliberately much slower than HEARTBEAT_INTERVAL_SECONDS --
# it's a periodic "everything's healthy" summary, not a per-tick line.
STATUS_PANEL_INTERVAL_SECONDS = 15.0

# Previous odds snapshot per (bookmaker, home, away, market, side), used
# only to detect and log an actual odds VALUE change (see
# _log_odds_changes below). Deliberately excludes OnWin -- OnWin is
# frozen and already has its own update logging in _onwin_worker_main.
_previous_odds: dict[tuple, tuple[float, float, float]] = {}


def _check_feed_freshness(name: str, age, now: float) -> bool:
    """
    Prints a rate-limited warning if `age` (seconds since last
    successful update, or None if never updated) looks unhealthy.

    Returns True if the feed should be treated as STALE and excluded
    from this tick's arbitrage calculation.
    """

    warn_key = f"{name.lower()}_last_warn_at"
    last_warn = _engine_monitor.get(warn_key, 0.0)

    if age is None:
        if now - last_warn > STALE_WARNING_REPEAT_SECONDS:
            print(f"[WARNING] {name} feed has not published any data yet.")
            _engine_monitor[warn_key] = now
        return True

    if age > MAX_ODDS_AGE_SECONDS:
        if now - last_warn > STALE_WARNING_REPEAT_SECONDS:
            print(
                f"[WARNING] {name} feed appears stale "
                f"(age={age:.1f}s) -- excluding from arbitrage calc."
            )
            _engine_monitor[warn_key] = now
        return True

    if age > WARN_ODDS_AGE_SECONDS:
        if now - last_warn > STALE_WARNING_REPEAT_SECONDS:
            print(f"[WARNING] {name} feed age={age:.1f}s")
            _engine_monitor[warn_key] = now

    return False


def _format_age(age):
    return f"{age:.1f}s" if age is not None else "n/a"


def _match_age_seconds(match, now_dt: datetime) -> float | None:
    """
    Seconds between `match.collected_at` and `now_dt`, or None if the
    match carries no timestamp at all (never treated as stale in that
    case -- absence of a timestamp is not evidence of staleness).
    """

    collected_at = match.collected_at

    if collected_at is None:
        return None

    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)

    return (now_dt - collected_at).total_seconds()


def _filter_stale_matches(matches, now_dt: datetime):
    """
    Per-MATCH (not just per-feed) freshness guard.

    A bookmaker's overall feed can look perfectly healthy (frequent
    "last_update_at" touches) while ONE specific match's own odds
    haven't actually changed/been reconfirmed in a long time -- e.g. a
    quiet market on a push-based feed. This is a second, finer-grained
    layer on top of the whole-feed staleness check above: it excludes
    only the individual matches that are actually old, not an entire
    bookmaker just because ONE of its matches is stale.

    Returns (fresh_matches, stale_count).
    """

    fresh = []
    stale_count = 0

    for match in matches:
        age = _match_age_seconds(match, now_dt)

        if age is not None and age > MAX_ODDS_AGE_SECONDS:
            stale_count += 1
            continue

        fresh.append(match)

    return fresh, stale_count


def _log_odds_changes(matches, interesting_events):
    """
    Prints "[BOOKMAKER] Home vs Away\n  SIDE old -> new" whenever a
    BetKanyon/Orbit price actually changes value from what was
    previously seen.

    Deliberately restricted to `interesting_events` (events currently
    matched against at least one OTHER bookmaker) rather than every
    single one of Orbit's ~100+ live markets: logging every raw tick
    across every market Orbit happens to be subscribed to -- most of
    which have no second bookmaker to arbitrage against at all -- would
    flood the terminal in exactly the way the spec asks to avoid,
    while still giving visual proof that fresh (not cached/repeated)
    data is flowing for the markets that actually matter to this
    engine.
    """

    for match in matches:

        if match.bookmaker == "OnWin":
            continue  # OnWin logs its own updates; frozen, not duplicated here.

        key_event = (match.home_team, match.away_team)
        if key_event not in interesting_events:
            continue

        key = (match.bookmaker, match.home_team, match.away_team, match.market, match.side)
        current = (match.home_odds, match.draw_odds, match.away_odds)
        previous = _previous_odds.get(key)

        _previous_odds[key] = current

        if previous is None or previous == current:
            continue

        side_label = f" ({match.side})" if match.side else ""
        print(f"[{match.bookmaker.upper()}]{side_label} {match.home_team} vs {match.away_team}")

        outcome_names = ("HOME", "DRAW", "AWAY")
        for name, old, new in zip(outcome_names, previous, current):
            if old != new:
                print(f"  {name} {old} -> {new}")


def _print_status_panel(
    onwin_status, betkanyon_status, orbit_status,
    onwin_age, betkanyon_age, orbit_age,
    matched_count, arb_count,
):
    mon = _engine_monitor

    print()
    print("=" * 60)
    print("WOUNDED LION ENERGY -- LIVE SCANNER")
    print("=" * 60)
    print()
    print(f"ONWIN       : {onwin_status.get('status', 'unknown').upper()}")
    print(f"              Status: {onwin_status.get('status')}")
    print(f"              Last update: {_format_age(onwin_age)} ago")
    print(f"              Events: {onwin_status.get('event_count', 0)}")
    print()
    print(f"BETKANYON   : {betkanyon_status.get('status', 'unknown').upper()}")
    print(f"              Last update: {_format_age(betkanyon_age)} ago")
    print(f"              Odds: {betkanyon_status.get('last_odds_count', 0)}")
    print(
        f"              Avg processing: "
        f"{betkanyon_status.get('avg_processing_ms') or 0:.0f}ms"
    )
    print()
    print(f"ORBIT       : {orbit_status.get('status', 'unknown').upper()}")
    print(f"              Last update: {_format_age(orbit_age)} ago")
    print(f"              Markets: {orbit_status.get('market_count', 0)}")
    print(
        f"              BACK odds: {orbit_status.get('back_count', 0)} | "
        f"LAY odds: {orbit_status.get('lay_count', 0)}"
    )
    print()
    print("ENGINE      : ACTIVE")
    print()
    print(f"MATCHED     : {matched_count}")
    print(f"ARBITRAGES  : {arb_count}")

    latest = mon.get("latest_arbitrage")
    if latest is not None:
        print()
        print("Latest arb:")
        print("-" * 60)
        print(latest)
        print("-" * 60)

    print("=" * 60)
    print()


def _print_arbitrage_opportunity(opportunity: ArbitrageOpportunity):
    event = opportunity.event
    result = opportunity.result
    plan = opportunity.stake_plan
    best = result.best_odds

    print()
    print("=" * 60)
    print("ARBITRAGE FOUND")
    print("=" * 60)
    print(f"Match: {event.home_team} vs {event.away_team}")
    print(f"Competition: {event.competition}")
    print()
    print(f"{'Bookmaker':<15}{'Side':<8}{'Selection':<12}{'Odds':<8}{'Stake':<10}")

    legs = (
        (plan.home, best.home_match),
        (plan.draw, best.draw_match),
        (plan.away, best.away_match),
    )

    for leg, source in legs:
        print(
            f"{leg.bookmaker:<15}{(source.side or '-'):<8}{leg.outcome:<12}"
            f"{leg.odds:<8}{leg.stake:<10}"
        )
    print()
    print(f"Arbitrage   : {result.profit_percentage:.2f}%")
    print(f"Total stake : {plan.total_stake}")
    print(f"Profit      : {plan.guaranteed_profit}")
    print(f"ROI         : {plan.roi:.2f}%")
    print("=" * 60)
    print()

    summary_lines = [f"{event.home_team} vs {event.away_team}", ""]
    for leg, source in legs:
        side_label = f" ({source.side})" if source.side else ""
        summary_lines.append(
            f"{leg.outcome}: {leg.bookmaker}{side_label} @ {leg.odds}"
        )
    summary_lines.append(f"Arbitrage: {result.profit_percentage:.2f}%")
    _engine_monitor["latest_arbitrage"] = "\n".join(summary_lines)


def _print_back_lay_opportunity(opportunity):
    print(f"[BACK-LAY] event={opportunity.home_team} vs {opportunity.away_team}")
    print(f"[BACK-LAY] outcome={opportunity.outcome}")
    print(f"[BACK-LAY] BACK {opportunity.back_bookmaker} @ {opportunity.back_odds}")
    print(f"[BACK-LAY] LAY {opportunity.lay_bookmaker} @ {opportunity.lay_odds}")
    print("[BACK-LAY] OPPORTUNITY")


def _iso_dt(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _write_cache(opportunities, generated_at_dt=None, back_lay_opportunities=None):

    generated_at_dt = generated_at_dt or datetime.now(timezone.utc)

    cache = []
    for back_lay in back_lay_opportunities or []:
        cache.append(back_lay.to_api_dict())

    for opportunity in opportunities:

        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan
        best = result.best_odds

        # API/CACHE-stage trace: this is the exact value api.py will
        # return byte-for-byte via /opportunities, so tracing it here
        # closes the RAW -> PARSED -> ENGINE -> API loop. Each leg may
        # be a different bookmaker, so each is traced with its OWN
        # full odds row (not the composite "best" triple).
        for match in (best.home_match, best.draw_match, best.away_match):
            odds_trace.record(
                "API",
                match.bookmaker,
                event.home_team,
                event.away_team,
                event.market,
                match.side,
                match.home_odds,
                match.draw_odds,
                match.away_odds,
            )

        cache.append(
            {
                "opportunityType": "BACK_BACK",
                "sport": event.sport,
                "competition": event.competition,
                "market": event.market,

                "homeTeam": event.home_team,
                "awayTeam": event.away_team,

                "profitPercentage": round(
                    result.profit_percentage,
                    2,
                ),

                "impliedProbability": round(
                    result.implied_probability,
                    4,
                ),

                "roi": plan.roi,
                "guaranteedProfit": plan.guaranteed_profit,
                "guaranteedReturn": plan.guaranteed_return,
                "totalStake": plan.total_stake,

                # When this specific opportunity was computed by the
                # engine -- the "timestamp of processing" the spec
                # asks every opportunity to carry.
                "generatedAt": _iso_dt(generated_at_dt),

                "home": {
                    "bookmaker": best.home_match.bookmaker,
                    "odds": best.home_match.home_odds,
                    "stake": plan.home.stake,
                    "side": best.home_match.side,
                    "market": best.home_match.market,
                    "collectedAt": _iso_dt(best.home_match.collected_at),
                },

                "draw": {
                    "bookmaker": best.draw_match.bookmaker,
                    "odds": best.draw_match.draw_odds,
                    "stake": plan.draw.stake,
                    "side": best.draw_match.side,
                    "market": best.draw_match.market,
                    "collectedAt": _iso_dt(best.draw_match.collected_at),
                },

                "away": {
                    "bookmaker": best.away_match.bookmaker,
                    "odds": best.away_match.away_odds,
                    "stake": plan.away.stake,
                    "side": best.away_match.side,
                    "market": best.away_match.market,
                    "collectedAt": _iso_dt(best.away_match.collected_at),
                },
            }
        )

    if not cache and CACHE_FILE.exists():
        return

    _atomic_write_text(
        CACHE_FILE,
        json.dumps(
            cache,
            indent=4,
            ensure_ascii=False,
        ),
    )


# ============================================================
# MAIN COLLECTION PIPELINE
# ============================================================

async def collect_opportunities(bankroll=1000):
    """
    One engine tick: read whatever OnWin/BetKanyon/Orbit currently have
    published (no network/browser activity happens here), run the
    existing matching/arbitrage pipeline over it, and print/cache the
    result.

    Meant to be called frequently (see ENGINE_TICK_SECONDS) -- freshness
    comes from the three persistent workers publishing continuously in
    the background, NOT from this function's call frequency.
    """

    finder = MatchFinder()
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    calculator = StakeCalculator()
    back_lay_detector = BackLayDetector()

    await _ensure_workers_alive()

    now_dt = datetime.now(timezone.utc)
    if is_prematch_only():
        _run_prematch_tick(bankroll=bankroll, now_dt=now_dt)
        empty = {
            "matches": [],
            "status": "stopped",
            "error": None,
            "last_update_at": None,
            "last_attempt_at": None,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "reconnect_count": 0,
            "event_count": 0,
            "last_event_count": 0,
            "market_count": 0,
            "last_odds_count": 0,
        }
        _maybe_print_prematch_panel()
        _write_status(
            onwin_status=empty,
            betkanyon_status=empty,
            orbit_status=empty,
            onwin_age=None,
            betkanyon_age=None,
            orbit_age=None,
            matched_count=0,
            opportunity_count=0,
            now_dt=now_dt,
        )
        return []

    onwin_handle = None
    betkanyon_worker = None
    orbit_worker = None
    try:
        onwin_handle = _get_onwin_handle()
    except Exception as exc:
        print(f"[ONWIN] Unavailable this tick ({type(exc).__name__}: {exc})")
    try:
        betkanyon_worker = _get_betkanyon_worker()
    except Exception as exc:
        print(f"[BETKANYON] Unavailable this tick ({type(exc).__name__}: {exc})")
    try:
        orbit_worker = _get_orbit_worker()
    except Exception as exc:
        print(f"[ORBIT] Unavailable this tick ({type(exc).__name__}: {exc})")

    empty_status = {
        "matches": [],
        "status": "error",
        "error": "Worker is not running.",
        "last_update_at": None,
        "last_attempt_at": None,
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "reconnect_count": 0,
        "event_count": 0,
        "last_event_count": 0,
        "market_count": 0,
        "last_odds_count": 0,
    }

    # Cheap reads only: OnWin is a ~ms Manager IPC read from its
    # persistent process, BetKanyon/Orbit are lock-free in-memory
    # copies from their persistent thread/task. None of these trigger
    # acquisition.
    onwin_status = onwin_handle.status() if onwin_handle is not None else dict(empty_status)
    betkanyon_status = (
        betkanyon_worker.get_status() if betkanyon_worker is not None else dict(empty_status)
    )
    orbit_status = (
        orbit_worker.get_status() if orbit_worker is not None else dict(empty_status)
    )

    onwin_matches = list(onwin_status.get("matches") or [])
    betkanyon_matches = (
        betkanyon_worker.get_matches() if betkanyon_worker is not None else []
    )
    orbit_matches = orbit_worker.get_matches() if orbit_worker is not None else []

    now = time.time()

    onwin_last_update = onwin_status.get("last_update_at")
    betkanyon_last_update = betkanyon_status.get("last_update_at")
    orbit_last_update = orbit_status.get("last_update_at")

    onwin_age = (
        now - onwin_last_update if onwin_last_update else None
    )
    betkanyon_age = (
        now - betkanyon_last_update if betkanyon_last_update else None
    )
    orbit_age = (
        now - orbit_last_update if orbit_last_update else None
    )

    onwin_stale = _check_feed_freshness("OnWin", onwin_age, now)
    betkanyon_stale = _check_feed_freshness("BetKanyon", betkanyon_age, now)
    orbit_stale = _check_feed_freshness("Orbit", orbit_age, now)

    # --------------------------------------------------------
    # Combine bookmaker MatchOdds -- stale feeds are excluded so a
    # dead bookmaker can never masquerade as a live arbitrage leg. If
    # one bookmaker is stale/reconnecting, the others still fully
    # participate (independent failure, per spec).
    # --------------------------------------------------------

    matches = []

    if not onwin_stale:
        matches.extend(onwin_matches)

    if not betkanyon_stale:
        matches.extend(betkanyon_matches)

    if not orbit_stale:
        matches.extend(orbit_matches)

    # Live pipeline must never ingest prematch MatchOdds even if a
    # worker handle were accidentally shared.
    matches = [
        match
        for match in matches
        if getattr(match, "feed_type", "live") == "live"
    ]

    # Second, finer-grained pass: even within a healthy feed, drop any
    # INDIVIDUAL match whose own collected_at is too old (see
    # _filter_stale_matches docstring) so a stale single match can
    # never masquerade as a live arbitrage leg just because the rest
    # of its bookmaker's feed is fine.
    now_dt = datetime.now(timezone.utc)
    matches, stale_match_count = _filter_stale_matches(matches, now_dt)

    if stale_match_count:
        warn_key = "stale_matches_last_warn_at"
        last_warn = _engine_monitor.get(warn_key, 0.0)
        if now - last_warn > STALE_WARNING_REPEAT_SECONDS:
            print(
                f"[WARNING] Excluded {stale_match_count} individually stale "
                f"match(es) (age > {MAX_ODDS_AGE_SECONDS:.0f}s) from this tick."
            )
            _engine_monitor[warn_key] = now

    # --------------------------------------------------------
    # Decide whether this tick was actually "triggered" by fresh data
    # from any bookmaker (used only to decide what to print/cache,
    # never to skip the computation itself -- see ENGINE_TICK_SECONDS
    # rationale above).
    # --------------------------------------------------------

    mon = _engine_monitor

    onwin_triggered = (
        onwin_last_update is not None
        and onwin_last_update != mon["last_onwin_update_at"]
    )
    betkanyon_triggered = (
        betkanyon_last_update is not None
        and betkanyon_last_update != mon["last_betkanyon_update_at"]
    )
    orbit_triggered = (
        orbit_last_update is not None
        and orbit_last_update != mon["last_orbit_update_at"]
    )

    triggered = onwin_triggered or betkanyon_triggered or orbit_triggered

    mon["last_onwin_update_at"] = onwin_last_update
    mon["last_betkanyon_update_at"] = betkanyon_last_update
    mon["last_orbit_update_at"] = orbit_last_update

    ts = time.strftime("%H:%M:%S")

    if triggered:
        sources = []
        if onwin_triggered:
            sources.append("OnWin")
        if betkanyon_triggered:
            sources.append("BetKanyon")
        if orbit_triggered:
            sources.append("Orbit")

        print(f"[ENGINE] {ts} | {' + '.join(sources)} update | matching...")

    # --------------------------------------------------------
    # Existing engine pipeline, unchanged: MatchFinder ->
    # BestOddsSelector -> ArbitrageDetector -> StakeCalculator.
    #
    # BestOddsSelector raises NoBackableOddsError for an event whose
    # ONLY odds are an Orbit LAY quote (no ordinary BACK-style price
    # from any bookmaker) -- that event is skipped here rather than
    # silently comparing a LAY liability price as if it were a normal
    # bookmaker price (see engine/best_odds_selector.py).
    # --------------------------------------------------------

    matched_events = finder.find(matches)

    opportunities = []

    for event in matched_events:

        try:
            best = selector.select(event)
        except NoBackableOddsError:
            continue

        result = detector.detect(best)

        if not result.arbitrage_exists:
            continue

        stake_plan = calculator.calculate(
            result=result,
            bankroll=bankroll,
        )

        opportunities.append(
            ArbitrageOpportunity(
                event=event,
                result=result,
                stake_plan=stake_plan,
            )
        )

    # --------------------------------------------------------
    # Separate BACK-vs-LAY detection -- not merged into the 3-way
    # BACK-vs-BACK formula. Written to the cache with
    # opportunityType=BACK_LAY so the UI can render it first.
    # --------------------------------------------------------

    back_lay_opportunities = back_lay_detector.find(matches)

    # --------------------------------------------------------
    # Odds-change visibility: only for events currently matched
    # against at least one other bookmaker (see _log_odds_changes).
    # --------------------------------------------------------

    interesting_events = {
        (event.home_team, event.away_team)
        for event in matched_events
        if len(event.matches) >= 2
    }

    if betkanyon_triggered:
        _log_odds_changes(betkanyon_matches, interesting_events)
    if orbit_triggered:
        _log_odds_changes(orbit_matches, interesting_events)

    # --------------------------------------------------------
    # Visibility: short "triggered" line, or a periodic heartbeat --
    # never both, never spammed every tick.
    # --------------------------------------------------------

    if triggered:
        print(f"[ENGINE] {ts} | matches={len(matched_events)} | arbs={len(opportunities)}")
        mon["last_heartbeat_at"] = now

    elif now - mon["last_heartbeat_at"] >= HEARTBEAT_INTERVAL_SECONDS:
        print(
            f"[ENGINE] {ts} | OnWin age={_format_age(onwin_age)} | "
            f"BetKanyon age={_format_age(betkanyon_age)} | "
            f"Orbit age={_format_age(orbit_age)} | "
            f"matches={len(matched_events)} | arbs={len(opportunities)}"
        )
        mon["last_heartbeat_at"] = now

    if now - mon["last_status_panel_at"] >= STATUS_PANEL_INTERVAL_SECONDS:
        _print_status_panel(
            onwin_status, betkanyon_status, orbit_status,
            onwin_age, betkanyon_age, orbit_age,
            len(matched_events), len(opportunities),
        )
        mon["last_status_panel_at"] = now

    for opportunity in opportunities:
        _print_arbitrage_opportunity(opportunity)

    if triggered:
        for back_lay_opportunity in back_lay_opportunities:
            _print_back_lay_opportunity(back_lay_opportunity)

    # --------------------------------------------------------
    # Cache: only rewrite when something actually changed (or on the
    # very first tick, so the cache isn't left empty/missing) instead
    # of on every ~1s engine tick.
    # --------------------------------------------------------

    if triggered or not CACHE_FILE.exists():
        _write_cache(
            opportunities,
            generated_at_dt=now_dt,
            back_lay_opportunities=back_lay_opportunities,
        )

    _run_prematch_tick(bankroll=bankroll, now_dt=now_dt)

    _write_status(
        onwin_status=onwin_status,
        betkanyon_status=betkanyon_status,
        orbit_status=orbit_status,
        onwin_age=onwin_age,
        betkanyon_age=betkanyon_age,
        orbit_age=orbit_age,
        matched_count=len(matched_events),
        opportunity_count=len(opportunities),
        now_dt=now_dt,
    )

    return opportunities


_prematch_panel_at = 0.0


def _maybe_print_prematch_panel():
    global _prematch_panel_at
    now = time.monotonic()
    if now - _prematch_panel_at < STATUS_PANEL_INTERVAL_SECONDS:
        return
    _prematch_panel_at = now
    bk = (
        _betkanyon_prematch_worker.get_status()
        if _betkanyon_prematch_worker is not None
        else {}
    )
    orbit = (
        _orbit_prematch_worker.get_status()
        if _orbit_prematch_worker is not None
        else {}
    )
    k90 = (
        _kolay90_prematch_worker.get_status()
        if _kolay90_prematch_worker is not None
        else {}
    )
    onwin = (
        _onwin_prematch_worker.get_status()
        if _onwin_prematch_worker is not None
        else {}
    )
    orbit_feed_stats = {}
    if _orbit_prematch_worker is not None and getattr(
        _orbit_prematch_worker, "_feed", None
    ) is not None:
        orbit_feed_stats = getattr(_orbit_prematch_worker._feed, "stats", {}) or {}
    bk_age = None
    if bk.get("last_update_at"):
        bk_age = time.time() - bk["last_update_at"]
    print()
    print("=" * 50)
    print("PREMATCH ENGINE")
    print("=" * 50)
    print(
        f"[BETKANYON] Browser: {str(bk.get('status', 'stopped')).upper()} "
        f"| Last payload: {bk_age:.0f}s ago" if bk_age is not None
        else f"[BETKANYON] Browser: {str(bk.get('status', 'stopped')).upper()}"
    )
    print(
        f"[BETKANYON] Events: {bk.get('last_event_count', 0)} "
        f"| Valid 1X2: {bk.get('last_odds_count', 0)}"
    )
    print(f"[ORBIT] Session: {str(orbit.get('status', 'stopped')).upper()}")
    print(
        f"[ORBIT] REST events: {orbit_feed_stats.get('rest_markets', 0)} "
        f"| WS frames: {orbit_feed_stats.get('ws_frames', 0)} "
        f"| WS odds: {orbit_feed_stats.get('ws_odds_frames', 0)}"
    )
    print(
        f"[ORBIT] Final events: {orbit.get('last_event_count', 0)} "
        f"| BACK: {orbit.get('back_count', 0)} "
        f"| LAY: {orbit.get('lay_count', 0)}"
    )
    print(
        f"BETKANYON PREMATCH: {str(bk.get('status', 'stopped')).upper()} "
        f"| events={bk.get('last_event_count', 0)} "
        f"| 1X2={bk.get('last_odds_count', 0)} "
        f"| age={bk_age:.0f}s" if bk_age is not None
        else f"BETKANYON PREMATCH: {str(bk.get('status', 'stopped')).upper()} | events={bk.get('last_event_count', 0)} | 1X2={bk.get('last_odds_count', 0)} | age=?"
    )
    orbit_age = None
    if orbit.get("last_update_at"):
        orbit_age = time.time() - orbit["last_update_at"]
    print(
        f"ORBIT PREMATCH: {str(orbit.get('status', 'stopped')).upper()} "
        f"| events={orbit.get('last_event_count', 0)} "
        f"| 1X2={orbit.get('back_count', 0) + orbit.get('lay_count', 0)} "
        f"| age={orbit_age:.0f}s" if orbit_age is not None
        else f"ORBIT PREMATCH: {str(orbit.get('status', 'stopped')).upper()} | events={orbit.get('last_event_count', 0)} | 1X2={orbit.get('back_count', 0) + orbit.get('lay_count', 0)} | age=?"
    )
    k90_age = None
    if k90.get("last_update_at"):
        k90_age = time.time() - k90["last_update_at"]
    print(
        f"KOLAY90 PREMATCH: {str(k90.get('status', 'stopped')).upper()} "
        f"| events={k90.get('last_event_count', 0)} "
        f"| 1X2={k90.get('last_odds_count', 0)} "
        f"| age={k90_age:.0f}s" if k90_age is not None
        else f"KOLAY90 PREMATCH: {str(k90.get('status', 'stopped')).upper()} | events={k90.get('last_event_count', 0)} | 1X2={k90.get('last_odds_count', 0)} | age=?"
    )
    onwin_age = None
    if onwin.get("last_update_at"):
        onwin_age = time.time() - onwin["last_update_at"]
    print(
        f"ONWIN PREMATCH: {str(onwin.get('status', 'stopped')).upper()} "
        f"| events={onwin.get('last_event_count', 0)} "
        f"| 1X2={onwin.get('last_odds_count', 0)} "
        f"| age={onwin_age:.0f}s" if onwin_age is not None
        else f"ONWIN PREMATCH: {str(onwin.get('status', 'stopped')).upper()} | events={onwin.get('last_event_count', 0)} | 1X2={onwin.get('last_odds_count', 0)} | age=?"
    )
    print(f"MATCHED: {_prematch_last_matched}")
    print(f"BACK/LAY ARBS: {_prematch_last_back_lay}")
    print(f"BACK/BACK ARBS: {_prematch_last_opportunities}")
    print(
        f"TOTAL ARBS: {_prematch_last_back_lay + _prematch_last_opportunities}"
    )
    print("=" * 50)
    print()


def _prematch_zero_reason(bk_n, orbit_n, matched_n, stale_n, total_arbs, kolay90_n=0, onwin_n=None):
    if total_arbs > 0:
        return "qualifying_arbs"
    if bk_n == 0 and orbit_n == 0 and kolay90_n == 0 and (onwin_n or 0) == 0:
        return "both_feeds_empty"
    if bk_n == 0:
        return "betkanyon_empty"
    if orbit_n == 0:
        return "orbit_empty"
    # onwin_n is None unless the OnWin prematch worker is running, so
    # existing BK+Orbit reason tests stay unchanged.
    if onwin_n == 0:
        return "onwin_empty"
    if matched_n == 0:
        return "matcher_no_pairs"
    if stale_n:
        return "stale_filter"
    return "no_qualifying_prices"


def _run_prematch_tick(bankroll, now_dt):
    """Match/arbitrage prematch feeds only. Never mixes live MatchOdds."""
    global _prematch_last_matched, _prematch_last_opportunities
    global _prematch_last_back_lay, _prematch_back_lay_sig
    global _prematch_last_cache_n

    if (
        _betkanyon_prematch_worker is None
        and _orbit_prematch_worker is None
        and _kolay90_prematch_worker is None
        and _onwin_prematch_worker is None
    ):
        return

    matches = []
    if _betkanyon_prematch_worker is not None:
        matches.extend(_betkanyon_prematch_worker.get_matches())
    if _orbit_prematch_worker is not None:
        matches.extend(_orbit_prematch_worker.get_matches())
    if _onwin_prematch_worker is not None:
        matches.extend(_onwin_prematch_worker.get_matches())
    if _kolay90_prematch_worker is not None:
        matches.extend(_kolay90_prematch_worker.get_matches())
    matches = [
        match
        for match in matches
        if getattr(match, "feed_type", "prematch") == "prematch"
    ]
    matches, stale_dropped = _filter_prematch_stale(matches, now_dt)
    bk_matches = [m for m in matches if m.bookmaker.lower() == "betkanyon"]
    orbit_matches = [m for m in matches if m.bookmaker.lower() == "orbit"]
    kolay90_matches = [m for m in matches if m.bookmaker.lower() == "kolay90"]
    onwin_matches = [m for m in matches if m.bookmaker.lower() == "onwin"]
    orbit_back = sum(1 for m in orbit_matches if (m.side or "").upper() == "BACK")
    orbit_lay = sum(1 for m in orbit_matches if (m.side or "").upper() == "LAY")
    try:
        matched_events, opportunities = build_prematch_opportunities(
            matches, bankroll=bankroll
        )
    except Exception as exc:
        print(
            f"[PREMATCH] matching failed ({type(exc).__name__}: {exc}); "
            "live pipeline unaffected"
        )
        return

    back_lay = []
    try:
        back_lay = find_prematch_back_lay(matches, log=False)
    except Exception as exc:
        print(
            f"[BACK-LAY] detector failed ({type(exc).__name__}: {exc}); "
            "BACK-vs-BACK unaffected"
        )

    matched_n = len(matched_events)
    arb_n = len(opportunities)
    back_lay_n = len(back_lay)
    total_arbs = arb_n + back_lay_n
    reason = _prematch_zero_reason(
        len(bk_matches),
        len(orbit_matches),
        matched_n,
        stale_dropped,
        total_arbs,
        kolay90_n=len(kolay90_matches),
        onwin_n=(
            len(onwin_matches) if _onwin_prematch_worker is not None else None
        ),
    )
    if (
        matched_n != _prematch_last_matched
        or arb_n != _prematch_last_opportunities
        or back_lay_n != _prematch_last_back_lay
        or stale_dropped
    ):
        print(
            f"[BETKANYON PREMATCH] cycle matches={len(bk_matches)} "
            f"unique={len({(m.home_team, m.away_team) for m in bk_matches})}"
        )
        print(
            f"[ORBIT PREMATCH] cycle matches={len(orbit_matches)} "
            f"BACK={orbit_back} LAY={orbit_lay} "
            f"unique={len({(m.home_team, m.away_team) for m in orbit_matches})}"
        )
        print(
            f"[ONWIN PREMATCH] cycle matches={len(onwin_matches)} "
            f"unique={len({(m.home_team, m.away_team) for m in onwin_matches})}"
        )
        print(
            f"[MATCHER] matched={matched_n} stale_rejected={stale_dropped} "
            f"bk={len(bk_matches)} orbit={len(orbit_matches)} "
            f"onwin={len(onwin_matches)} kolay90={len(kolay90_matches)}"
        )
        print(
            f"[ARB] BACK/LAY={back_lay_n} BACK/BACK={arb_n} "
            f"TOTAL={total_arbs} reason={reason}"
        )
    _prematch_last_matched = matched_n
    _prematch_last_opportunities = arb_n
    _prematch_last_back_lay = back_lay_n
    back_lay_sig = tuple(
        sorted(
            (
                item.home_team,
                item.away_team,
                item.outcome,
                item.back_bookmaker,
                item.back_odds,
                item.lay_bookmaker,
                item.lay_odds,
            )
            for item in back_lay
        )
    )
    if back_lay_sig != _prematch_back_lay_sig:
        for item in back_lay:
            _print_back_lay_opportunity(item)
        _prematch_back_lay_sig = back_lay_sig
    _maybe_print_prematch_panel()
    cache = serialize_prematch_cache(
        back_lay, opportunities, generated_at_dt=now_dt
    )
    feed_gap = reason in {
        "both_feeds_empty",
        "betkanyon_empty",
        "orbit_empty",
        "onwin_empty",
    }
    if not should_replace_snapshot(cache, _prematch_last_cache_n, feeds_ready=not feed_gap):
        if _prematch_last_cache_n > 0:
            print(
                f"[ARB] cache kept ({_prematch_last_cache_n} last-good); "
                f"this cycle is {reason}, not a genuine zero-arb book"
            )
        return
    _prematch_last_cache_n = len(cache)
    _atomic_write_text(
        PREMATCH_CACHE_FILE,
        json.dumps(cache, indent=4, ensure_ascii=False),
    )


def _worker_alive(process_or_thread_or_task) -> bool:
    if process_or_thread_or_task is None:
        return False

    is_alive = getattr(process_or_thread_or_task, "is_alive", None)
    if is_alive is not None:
        return is_alive()

    done = getattr(process_or_thread_or_task, "done", None)
    if done is not None:
        return not done()

    return True


def _split_error(error: str | None) -> tuple[str | None, str | None]:
    """
    Split a worker's 'TypeName: message' error string into
    (last_error_type, last_error) without ever treating the text as a
    secret. Workers already store only type+message, never credentials.
    """
    if not error:
        return None, None
    type_name, sep, _rest = error.partition(": ")
    if sep:
        return type_name, error
    return None, error


def _collector_snapshot(name, raw_status, age, alive, status_dict, now_dt, max_age=None):
    consecutive_failures = status_dict.get("consecutive_failures", 0) or 0
    consecutive_successes = status_dict.get("consecutive_successes", 0) or 0
    reconnect_count = status_dict.get("reconnect_count", 0) or 0
    last_error_type, last_error = _split_error(status_dict.get("error"))
    records_collected = (
        status_dict.get("event_count")
        or status_dict.get("last_event_count")
        or status_dict.get("market_count")
        or 0
    )

    return {
        "name": name,
        "collectorStatus": _classify_collector_status(
            raw_status,
            age,
            alive,
            consecutive_failures=consecutive_failures,
            consecutive_successes=consecutive_successes,
            reconnect_count=reconnect_count,
            max_age=max_age,
        ),
        "rawStatus": raw_status,
        "workerAlive": bool(alive),
        "error": last_error,
        "lastError": last_error,
        "lastErrorType": last_error_type,
        "lastSuccessfulCollection": _iso(status_dict.get("last_update_at")),
        "lastCollectionAttempt": _iso(status_dict.get("last_attempt_at")),
        "lastAttempt": _iso(status_dict.get("last_attempt_at")),
        "lastSuccess": _iso(status_dict.get("last_update_at")),
        "ageSeconds": round(age, 1) if age is not None else None,
        "dataAge": round(age, 1) if age is not None else None,
        "eventsCollected": records_collected,
        "recordsCollected": records_collected,
        # Metrics per the "measure before changing" spec: enough to
        # distinguish "genuinely down" (sustained consecutive_failures,
        # rising reconnectCount, stale age) from "just retried once and
        # recovered" (a lone failure immediately followed by a success)
        # without inferring either from opportunity count.
        "metrics": {
            "consecutiveFailures": consecutive_failures,
            "consecutiveSuccesses": consecutive_successes,
            "reconnectCount": reconnect_count,
            "requestCount": (
                status_dict.get("request_count")
                or status_dict.get("poll_count")
                or status_dict.get("frame_count")
                or 0
            ),
            "successCount": status_dict.get("success_count", 0) or 0,
            "failedCount": status_dict.get("failed_count", 0) or 0,
            "avgProcessingMs": status_dict.get("avg_processing_ms"),
        },
        "consecutiveFailures": consecutive_failures,
        "consecutiveSuccesses": consecutive_successes,
        "reconnectCount": reconnect_count,
        "phase": status_dict.get("phase"),
    }


def _write_status(
    onwin_status, betkanyon_status, orbit_status,
    onwin_age, betkanyon_age, orbit_age,
    matched_count, opportunity_count, now_dt,
):
    """
    Writes collector/engine health to STATUS_FILE every tick so a
    separate process (api.py) can expose it via /status WITHOUT
    starting its own copy of the OnWin/BetKanyon/Orbit workers.

    Deliberately includes NO opportunity-derived signal in any
    collector's own status -- opportunity_count is reported once, at
    the top level, entirely separate from each collector's health, so
    "0 opportunities" can never be misread as "a collector stopped".
    """

    onwin_alive = _worker_alive(_onwin_handle._process if _onwin_handle else None)
    betkanyon_alive = _worker_alive(
        _betkanyon_worker._thread if _betkanyon_worker else None
    )
    orbit_alive = _worker_alive(_orbit_worker._task if _orbit_worker else None)
    now = now_dt.timestamp() if hasattr(now_dt, "timestamp") else time.time()
    bk_pm_status = (
        _betkanyon_prematch_worker.get_status()
        if _betkanyon_prematch_worker is not None
        else {"status": "stopped", "error": None, "last_update_at": None}
    )
    orbit_pm_status = (
        _orbit_prematch_worker.get_status()
        if _orbit_prematch_worker is not None
        else {"status": "stopped", "error": None, "last_update_at": None}
    )
    k90_pm_status = (
        _kolay90_prematch_worker.get_status()
        if _kolay90_prematch_worker is not None
        else {"status": "stopped", "error": None, "last_update_at": None}
    )
    onwin_pm_status = (
        _onwin_prematch_worker.get_status()
        if _onwin_prematch_worker is not None
        else {"status": "stopped", "error": None, "last_update_at": None}
    )
    bk_pm_last = bk_pm_status.get("last_update_at")
    orbit_pm_last = orbit_pm_status.get("last_update_at")
    k90_pm_last = k90_pm_status.get("last_update_at")
    onwin_pm_last = onwin_pm_status.get("last_update_at")
    bk_pm_age = (now - bk_pm_last) if bk_pm_last else None
    orbit_pm_age = (now - orbit_pm_last) if orbit_pm_last else None
    k90_pm_age = (now - k90_pm_last) if k90_pm_last else None
    onwin_pm_age = (now - onwin_pm_last) if onwin_pm_last else None

    payload = {
        "generatedAt": _iso_dt(now_dt),
        "matchedEvents": matched_count,
        "opportunityCount": opportunity_count,
        "prematchMatchedEvents": _prematch_last_matched,
        "prematchOpportunityCount": _prematch_last_opportunities,
        "engineMode": engine_mode_label(),
        "scheduledRestart": scheduled_restart_active(),
        "collectors": {
            "onwin": _collector_snapshot(
                "OnWin", onwin_status.get("status"), onwin_age,
                onwin_alive, onwin_status, now_dt,
            ),
            "betkanyon": _collector_snapshot(
                "BetKanyon", betkanyon_status.get("status"), betkanyon_age,
                betkanyon_alive, betkanyon_status, now_dt,
            ),
            "orbit": _collector_snapshot(
                "Orbit", orbit_status.get("status"), orbit_age,
                orbit_alive, orbit_status, now_dt,
            ),
            "betkanyon_prematch": _collector_snapshot(
                "BetKanyon Prematch",
                bk_pm_status.get("status"),
                bk_pm_age,
                _worker_alive(
                    _betkanyon_prematch_worker._thread
                    if _betkanyon_prematch_worker
                    else None
                ),
                bk_pm_status,
                now_dt,
                max_age=PREMATCH_MAX_ODDS_AGE_SECONDS,
            ),
            "orbit_prematch": _collector_snapshot(
                "Orbit Prematch",
                orbit_pm_status.get("status"),
                orbit_pm_age,
                _worker_alive(
                    _orbit_prematch_worker._task
                    if _orbit_prematch_worker
                    else None
                ),
                orbit_pm_status,
                now_dt,
                max_age=PREMATCH_MAX_ODDS_AGE_SECONDS,
            ),
            "kolay90_prematch": _collector_snapshot(
                "Kolay90 Prematch",
                k90_pm_status.get("status"),
                k90_pm_age,
                _worker_alive(
                    _kolay90_prematch_worker._thread
                    if _kolay90_prematch_worker
                    else None
                ),
                k90_pm_status,
                now_dt,
                max_age=PREMATCH_MAX_ODDS_AGE_SECONDS,
            ),
            "onwin_prematch": _collector_snapshot(
                "OnWin Prematch",
                onwin_pm_status.get("status"),
                onwin_pm_age,
                _worker_alive(
                    _onwin_prematch_worker._thread
                    if _onwin_prematch_worker
                    else None
                ),
                onwin_pm_status,
                now_dt,
                max_age=PREMATCH_MAX_ODDS_AGE_SECONDS,
            ),
        },
    }

    _atomic_write_text(
        STATUS_FILE,
        json.dumps(payload, indent=4, ensure_ascii=False),
    )


# ============================================================
# CACHE
# ============================================================

def get_cached_opportunities():

    if not CACHE_FILE.exists():
        return []

    return json.loads(
        CACHE_FILE.read_text(
            encoding="utf-8"
        )
    )


def get_cached_prematch_opportunities():
    if not PREMATCH_CACHE_FILE.exists():
        return []
    return json.loads(PREMATCH_CACHE_FILE.read_text(encoding="utf-8"))


def get_collector_status():
    """
    Read-only, cross-process view of collector/engine health for
    api.py's /status endpoint.

    Purely reads STATUS_FILE (written by the engine process every
    tick -- see _write_status()) -- never starts/touches any worker
    itself, so calling this from the API process never has the side
    effect of spinning up a second, redundant set of OnWin/BetKanyon/
    Orbit workers.
    """

    if not STATUS_FILE.exists():
        return {
            "generatedAt": None,
            "matchedEvents": 0,
            "opportunityCount": 0,
            "scheduledRestart": scheduled_restart_active(),
            "collectors": {
                name: {
                    "name": label,
                    "collectorStatus": CollectorStatus.STOPPED.value,
                    "rawStatus": None,
                    "error": "Engine has not published a status snapshot yet.",
                    "lastSuccessfulCollection": None,
                    "lastCollectionAttempt": None,
                    "ageSeconds": None,
                    "eventsCollected": 0,
                }
                for name, label in (
                    ("onwin", "OnWin"),
                    ("betkanyon", "BetKanyon"),
                    ("orbit", "Orbit"),
                    ("betkanyon_prematch", "BetKanyon Prematch"),
                    ("orbit_prematch", "Orbit Prematch"),
                    ("onwin_prematch", "OnWin Prematch"),
                    ("kolay90_prematch", "Kolay90 Prematch"),
                )
            },
        }

    payload = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    scheduled = bool(payload.get("scheduledRestart") or scheduled_restart_active())
    payload["scheduledRestart"] = scheduled
    if scheduled:
        collectors = payload.get("collectors") or {}
        for key, row in collectors.items():
            if isinstance(row, dict):
                updated = dict(row)
                updated["collectorStatus"] = display_collector_status(
                    updated.get("collectorStatus"), True
                )
                collectors[key] = updated
        payload["collectors"] = collectors
    return payload



