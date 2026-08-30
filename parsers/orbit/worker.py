"""
Persistent Orbit Exchange acquisition worker.

Unlike OnWin/BetKanyon, Orbit needs no browser at all: REST for the
market catalogue, then one persistent WebSocket (parsers/orbit/client.py)
that pushes price-update frames continuously and independently per
market -- genuinely event-driven, not a fixed-interval poll. So this
worker runs as a plain asyncio.Task on the SAME event loop as
run_engine.py's main loop (see collector.start_workers()), not a
separate thread/process like BetKanyon/OnWin needed for their
Playwright sessions.
"""

import asyncio
import time
from datetime import datetime

from engine.collector_health import (
    INPLACE_RETRY_PAUSE_SECONDS,
    MAX_INPLACE_RETRIES,
    is_connection_dead_error,
)
from parsers.orbit.feed import OrbitFeed


INITIAL_BACKOFF_SECONDS = 3
MAX_BACKOFF_SECONDS = 60

# Odds-freshness (distinct from socket liveness). Derived from the
# existing collector stale bar (collector.MAX_ODDS_AGE_SECONDS default
# 30s) and from live observation that a healthy Orbit book ticks far
# more often than that across ~200 subscribed markets. A warning fires
# earlier so a quiet stretch is visible before the feed is marked
# unhealthy. Neither threshold reconnects the websocket by itself --
# only socket silence / close does that.
ODDS_STALE_WARN_SECONDS = 12.0
ODDS_UNHEALTHY_SECONDS = 30.0
HEALTH_LOG_SECONDS = 15.0
RESUBSCRIBE_COOLDOWN_SECONDS = 20.0


class OrbitWorker:
    """
    Owns exactly ONE persistent Orbit WebSocket session (via one
    long-lived OrbitFeed) and reacts to incoming frames as they
    arrive, forever, until stop().

    Interface intentionally mirrors parsers.betkanyon.worker.BetkanyonWorker
    (get_matches()/get_status()/start()/stop()) so collector.py can
    treat all three bookmaker workers uniformly.
    """

    def __init__(self):
        self._feed = None
        self._task = None
        self._stop_requested = False
        self._last_health_log_at = 0.0
        self._last_stale_warn_at = 0.0
        self._odds_unhealthy_logged = False
        self._last_resubscribe_at = 0.0

        self._state = {
            "matches": [],
            "status": "starting",
            "error": None,
            "last_update_at": None,
            "last_attempt_at": None,
            "last_heartbeat_at": None,
            "frame_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "reconnect_count": 0,
            "last_processing_ms": None,
            "avg_processing_ms": None,
            "market_count": 0,
            "back_count": 0,
            "lay_count": 0,
            "feed_healthy": False,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._task is not None and not self._task.done():
            return

        print("[ORBIT] Starting persistent session...")

        self._stop_requested = False
        self._task = asyncio.create_task(self._run(), name="orbit-worker")

    async def stop(self, timeout=10):
        self._stop_requested = True

        if self._task is not None:
            self._task.cancel()

            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if self._feed is not None:
            try:
                await self._feed.close()
            except Exception:
                pass
            self._feed = None

        self._state["status"] = "stopped"

    # ------------------------------------------------------------------
    # Reads (called from the collector/engine side)
    # ------------------------------------------------------------------

    def get_matches(self):
        return list(self._state["matches"])

    def get_status(self):
        return dict(self._state)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _run(self):
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state["status"] = "error"
            self._state["error"] = f"{type(exc).__name__}: {exc}"
            print(
                f"[ORBIT] Worker task crashed "
                f"({type(exc).__name__}: {exc}). Supervisor will restart it."
            )

    async def _run_loop(self):
        backoff = INITIAL_BACKOFF_SECONDS

        while not self._stop_requested:

            self._state["last_attempt_at"] = time.time()

            failure_during_connect = False

            try:
                if self._feed is None:
                    self._state["status"] = "connecting"

                    self._feed = OrbitFeed()

                    failure_during_connect = True
                    market_count = await self._feed.connect_and_subscribe()
                    failure_during_connect = False

                    self._state["market_count"] = market_count

                    print(
                        f"[ORBIT] Session established | "
                        f"subscribed to {market_count} live markets"
                    )
                    print("[ORBIT] Feed healthy")

                cycle_start = time.monotonic()

                matches = await self._feed.receive_next()

                elapsed_ms = (time.monotonic() - cycle_start) * 1000
                kind = getattr(self._feed, "last_frame_kind", "odds")

                if kind == "heartbeat":
                    self._note_heartbeat()
                    await self._maybe_lightweight_recovery()
                elif kind == "odds":
                    self._publish_success(matches, elapsed_ms)
                    backoff = INITIAL_BACKOFF_SECONDS
                else:
                    self._note_activity()
                    await self._maybe_lightweight_recovery()

                self._maybe_log_health()

                await asyncio.sleep(0)

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                consecutive_failures = self._publish_failure(exc)

                # TimeoutError here means SOCKET_SILENCE_SECONDS with
                # no frames at all (heartbeats included). That is a
                # dead socket, not "prices were quiet".
                must_reconnect = (
                    failure_during_connect
                    or is_connection_dead_error(exc)
                    or consecutive_failures >= MAX_INPLACE_RETRIES
                )

                if must_reconnect:
                    self._state["status"] = "reconnecting"
                    self._state["reconnect_count"] += 1
                    self._state["feed_healthy"] = False

                    print(
                        f"[ORBIT] ERROR: Feed recovery needed "
                        f"({type(exc).__name__}: {exc})"
                    )
                    print(
                        f"[ORBIT] Recreating Orbit session in {backoff}s..."
                    )

                    if self._feed is not None:
                        try:
                            await self._feed.close()
                        except Exception:
                            pass
                        self._feed = None

                    try:
                        await asyncio.sleep(backoff)
                    except asyncio.CancelledError:
                        raise

                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    print("[ORBIT] Attempting recovery...")
                else:
                    print(
                        f"[ORBIT] Transient error "
                        f"({type(exc).__name__}: {exc}), retrying in "
                        f"place ({consecutive_failures}/{MAX_INPLACE_RETRIES})..."
                    )

                    try:
                        await asyncio.sleep(INPLACE_RETRY_PAUSE_SECONDS)
                    except asyncio.CancelledError:
                        raise

    def _note_heartbeat(self):
        now = time.time()
        self._state["last_heartbeat_at"] = now
        self._state["last_attempt_at"] = now
        self._state["frame_count"] += 1
        self._state["error"] = None
        if self._state["status"] == "connecting":
            self._state["status"] = "running"
        self._refresh_odds_health()

    def _note_activity(self):
        self._state["last_attempt_at"] = time.time()
        self._state["frame_count"] += 1
        self._refresh_odds_health()

    def _publish_success(self, new_matches, elapsed_ms):
        state = self._state

        state["status"] = "running"
        state["error"] = None
        state["last_update_at"] = time.time()
        state["frame_count"] += 1
        state["success_count"] += 1
        state["consecutive_failures"] = 0
        state["consecutive_successes"] += 1
        state["last_processing_ms"] = elapsed_ms

        prev_avg = state["avg_processing_ms"]
        n = state["success_count"]
        state["avg_processing_ms"] = (
            elapsed_ms if prev_avg is None
            else prev_avg + (elapsed_ms - prev_avg) / n
        )

        if self._feed is not None:
            all_matches = self._feed.get_match_odds()
            state["matches"] = all_matches
            state["back_count"] = sum(
                1 for m in all_matches if m.side == "BACK"
            )
            state["lay_count"] = sum(
                1 for m in all_matches if m.side == "LAY"
            )

        if state["success_count"] == 1:
            print("[ORBIT] Feed response received")

        recovered = self._odds_unhealthy_logged
        self._refresh_odds_health()
        if recovered and state["feed_healthy"]:
            print("[ORBIT] Feed recovered")
            self._odds_unhealthy_logged = False

    def _refresh_odds_health(self):
        last = self._state.get("last_update_at")
        if last is None:
            self._state["feed_healthy"] = False
            return

        age = time.time() - last
        now_mono = time.monotonic()

        if age >= ODDS_UNHEALTHY_SECONDS:
            self._state["feed_healthy"] = False
            if not self._odds_unhealthy_logged:
                print(
                    f"[ORBIT] WARNING: No valid feed update for {age:.1f}s"
                )
                print("[ORBIT] Feed marked unhealthy")
                self._odds_unhealthy_logged = True
            return

        self._state["feed_healthy"] = True

        if age >= ODDS_STALE_WARN_SECONDS:
            if now_mono - self._last_stale_warn_at >= ODDS_STALE_WARN_SECONDS:
                print(
                    f"[ORBIT] WARNING: No valid feed update for {age:.1f}s"
                )
                self._last_stale_warn_at = now_mono

    async def _maybe_lightweight_recovery(self):
        """
        Heartbeats still flowing but odds frozen: resubscribe on the
        SAME websocket. Do not open a second session.
        """
        if self._feed is None or not hasattr(self._feed, "resubscribe_all"):
            return

        last_odds = self._state.get("last_update_at")
        last_hb = self._state.get("last_heartbeat_at")
        if last_odds is None or last_hb is None:
            return
        if time.time() - last_odds < ODDS_STALE_WARN_SECONDS:
            return
        if time.time() - last_hb > 15:
            return

        now = time.monotonic()
        if now - self._last_resubscribe_at < RESUBSCRIBE_COOLDOWN_SECONDS:
            return

        self._last_resubscribe_at = now
        print("[ORBIT] Attempting recovery...")
        try:
            n = await self._feed.resubscribe_all()
            print(
                f"[ORBIT] Resubscribed {n} markets on existing session"
            )
        except Exception as exc:
            print(
                f"[ORBIT] ERROR: Page recovery failed "
                f"({type(exc).__name__}: {exc})"
            )
            raise

    def _maybe_log_health(self):
        now = time.monotonic()
        if now - self._last_health_log_at < HEALTH_LOG_SECONDS:
            return
        self._last_health_log_at = now

        last = self._state.get("last_update_at")
        if last is None:
            age_label = "n/a"
        else:
            age_label = f"{time.time() - last:.1f}s ago"

        healthy = "healthy" if self._state.get("feed_healthy") else "unhealthy"
        hb = self._state.get("last_heartbeat_at")
        hb_label = f"{time.time() - hb:.1f}s ago" if hb else "n/a"
        print(
            f"[ORBIT] {datetime.now().strftime('%H:%M:%S')} | "
            f"feed {healthy} | last odds {age_label} | "
            f"last heartbeat {hb_label} | "
            f"markets={self._state.get('market_count', 0)} "
            f"BACK={self._state.get('back_count', 0)} "
            f"LAY={self._state.get('lay_count', 0)}"
        )

    def _publish_failure(self, exc) -> int:
        """
        Records one failed cycle and returns the new consecutive
        failure count.

        Deliberately does NOT set status="reconnecting" here -- only
        true once the caller actually decides to reconnect.
        """
        state = self._state
        state["error"] = f"{type(exc).__name__}: {exc}"
        state["frame_count"] += 1
        state["failed_count"] += 1
        state["consecutive_successes"] = 0
        state["consecutive_failures"] += 1
        return state["consecutive_failures"]
