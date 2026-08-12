import json
import multiprocessing
import os
import time
from pathlib import Path

from engine.match_finder import MatchFinder
from engine.best_odds_selector import BestOddsSelector
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator
from models.arbitrage_opportunity import ArbitrageOpportunity

from parsers.betkanyon.worker import BetkanyonWorker
from parsers.onwin.feed import OnwinFeed


CACHE_FILE = Path("cached_opportunities.json")


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

def _onwin_worker_main(shared_state, stop_event):
    """
    Runs in its own process for the lifetime of the engine.

    shared_state (a multiprocessing.Manager dict) is how the collector
    reads the latest OnWin MatchOdds without any per-cycle browser
    activity: this worker publishes into it, the collector only reads
    from it.
    """

    feed = None
    backoff_seconds = 5
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

    def log_update(version, event_count, changed_count):
        # Called for EVERY processed find_event_snapshots response
        # (not just ones that changed something), so this doubles as
        # the feed's liveness signal.
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
                    print("[ONWIN] Reconnecting: creating a new browser/session...")

                feed = OnwinFeed()
                feed.start(on_change=publish, on_update=log_update)

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
                backoff_seconds = 5

            # Pumps the browser's message loop so queued
            # find_event_snapshots responses are actually delivered to
            # the update handler. Does not navigate or fetch anything.
            feed.poll(tick_ms=500)

        except Exception as exc:
            shared_state["status"] = "reconnecting"
            shared_state["error"] = f"{type(exc).__name__}: {exc}"

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

            time.sleep(min(backoff_seconds, 60))
            backoff_seconds = min(backoff_seconds * 2, 60)

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
        self.shared_state["error"] = None
        self.shared_state["last_update_at"] = None

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


def start_workers():
    """
    Explicitly start both persistent bookmaker workers up front so
    they begin acquiring data CONCURRENTLY, rather than each being
    lazily created on first use inside collect_opportunities() (which
    would work the same functionally, but this makes the "both feeds
    start together" intent explicit at startup).
    """

    _get_onwin_handle()
    _get_betkanyon_worker()


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
    "last_heartbeat_at": 0.0,
    "onwin_last_warn_at": 0.0,
    "betkanyon_last_warn_at": 0.0,
}


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


def _print_arbitrage_opportunity(opportunity: ArbitrageOpportunity):
    event = opportunity.event
    result = opportunity.result
    plan = opportunity.stake_plan

    print()
    print("=" * 60)
    print("ARBITRAGE FOUND")
    print("=" * 60)
    print(f"Match: {event.home_team} vs {event.away_team}")
    print(f"Competition: {event.competition}")
    print()
    print(f"{'Bookmaker':<15}{'Selection':<12}{'Odds':<8}{'Stake':<10}")
    for leg in (plan.home, plan.draw, plan.away):
        print(
            f"{leg.bookmaker:<15}{leg.outcome:<12}"
            f"{leg.odds:<8}{leg.stake:<10}"
        )
    print()
    print(f"Arbitrage   : {result.profit_percentage:.2f}%")
    print(f"Total stake : {plan.total_stake}")
    print(f"Profit      : {plan.guaranteed_profit}")
    print(f"ROI         : {plan.roi:.2f}%")
    print("=" * 60)
    print()


def _write_cache(opportunities):
    cache = []

    for opportunity in opportunities:

        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan
        best = result.best_odds

        cache.append(
            {
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

                "home": {
                    "bookmaker": best.home_match.bookmaker,
                    "odds": best.home_match.home_odds,
                    "stake": plan.home.stake,
                },

                "draw": {
                    "bookmaker": best.draw_match.bookmaker,
                    "odds": best.draw_match.draw_odds,
                    "stake": plan.draw.stake,
                },

                "away": {
                    "bookmaker": best.away_match.bookmaker,
                    "odds": best.away_match.away_odds,
                    "stake": plan.away.stake,
                },
            }
        )

    CACHE_FILE.write_text(
        json.dumps(
            cache,
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ============================================================
# MAIN COLLECTION PIPELINE
# ============================================================

async def collect_opportunities(bankroll=1000):
    """
    One engine tick: read whatever OnWin/BetKanyon currently have
    published (no network/browser activity happens here), run the
    existing matching/arbitrage pipeline over it, and print/cache the
    result.

    Meant to be called frequently (see ENGINE_TICK_SECONDS) -- freshness
    comes from the two persistent workers publishing continuously in
    the background, NOT from this function's call frequency.
    """

    finder = MatchFinder()
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    calculator = StakeCalculator()

    onwin_handle = _get_onwin_handle()
    betkanyon_worker = _get_betkanyon_worker()

    # Cheap reads only: OnWin is a ~ms Manager IPC read from its
    # persistent process, BetKanyon is a lock-protected in-memory copy
    # from its persistent thread. Neither triggers acquisition.
    onwin_status = onwin_handle.status()
    betkanyon_status = betkanyon_worker.get_status()

    onwin_matches = list(onwin_status.get("matches") or [])
    betkanyon_matches = betkanyon_worker.get_matches()

    now = time.time()

    onwin_last_update = onwin_status.get("last_update_at")
    betkanyon_last_update = betkanyon_status.get("last_update_at")

    onwin_age = (
        now - onwin_last_update if onwin_last_update else None
    )
    betkanyon_age = (
        now - betkanyon_last_update if betkanyon_last_update else None
    )

    onwin_stale = _check_feed_freshness("OnWin", onwin_age, now)
    betkanyon_stale = _check_feed_freshness("BetKanyon", betkanyon_age, now)

    # --------------------------------------------------------
    # Combine bookmaker MatchOdds -- stale feeds are excluded so a
    # dead bookmaker can never masquerade as a live arbitrage leg.
    # --------------------------------------------------------

    matches = []

    if not onwin_stale:
        matches.extend(onwin_matches)

    if not betkanyon_stale:
        matches.extend(betkanyon_matches)

    # --------------------------------------------------------
    # Decide whether this tick was actually "triggered" by fresh data
    # from either bookmaker (used only to decide what to print/cache,
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

    triggered = onwin_triggered or betkanyon_triggered

    mon["last_onwin_update_at"] = onwin_last_update
    mon["last_betkanyon_update_at"] = betkanyon_last_update

    ts = time.strftime("%H:%M:%S")

    if triggered:
        sources = []
        if onwin_triggered:
            sources.append("OnWin")
        if betkanyon_triggered:
            sources.append("BetKanyon")

        print(f"[ENGINE] {ts} | {' + '.join(sources)} update | matching...")

    # --------------------------------------------------------
    # Existing engine pipeline, unchanged: MatchFinder ->
    # BestOddsSelector -> ArbitrageDetector -> StakeCalculator.
    # --------------------------------------------------------

    matched_events = finder.find(matches)

    opportunities = []

    for event in matched_events:

        best = selector.select(event)

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
            f"matches={len(matched_events)} | arbs={len(opportunities)}"
        )
        mon["last_heartbeat_at"] = now

    for opportunity in opportunities:
        _print_arbitrage_opportunity(opportunity)

    # --------------------------------------------------------
    # Cache: only rewrite when something actually changed (or on the
    # very first tick, so the cache isn't left empty/missing) instead
    # of on every ~1s engine tick.
    # --------------------------------------------------------

    if triggered or not CACHE_FILE.exists():
        _write_cache(opportunities)

    return opportunities


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



