"""Persistent Orbit prematch worker.

Separate asyncio task and websocket from live Orbit. Live worker.py is
not imported.
"""

import asyncio
import time
from datetime import datetime

from engine.collector_health import (
    INPLACE_RETRY_PAUSE_SECONDS,
    MAX_INPLACE_RETRIES,
    is_connection_dead_error,
)
from parsers.orbit_prematch.feed import OrbitPrematchFeed


INITIAL_BACKOFF_SECONDS = 3
MAX_BACKOFF_SECONDS = 60
HEALTH_LOG_SECONDS = 20.0
ODDS_STALE_WARN_SECONDS = 45.0
RESUBSCRIBE_COOLDOWN_SECONDS = 30.0


class OrbitPrematchWorker:
    def __init__(self):
        self._feed = None
        self._task = None
        self._stop_requested = False
        self._last_health_log_at = 0.0
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

    def start(self):
        if self._task is not None and not self._task.done():
            return
        print("[ORBIT PREMATCH] STARTING")
        self._stop_requested = False
        self._task = asyncio.create_task(self._run(), name="orbit-prematch-worker")

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

    def get_matches(self):
        return list(self._state["matches"])

    def get_status(self):
        return dict(self._state)

    async def _run(self):
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state["status"] = "error"
            self._state["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[ORBIT PREMATCH] worker crashed ({type(exc).__name__}: {exc})")

    async def _run_loop(self):
        backoff = INITIAL_BACKOFF_SECONDS
        while not self._stop_requested:
            self._state["last_attempt_at"] = time.time()
            connecting = False
            try:
                if self._feed is None:
                    self._state["status"] = "connecting"
                    self._feed = OrbitPrematchFeed()
                    connecting = True
                    market_count = await self._feed.connect_and_subscribe()
                    connecting = False
                    self._state["market_count"] = market_count
                    print(f"[ORBIT PREMATCH] events parsed: {market_count} markets subscribed")

                cycle_start = time.monotonic()
                matches = await self._feed.receive_next()
                elapsed_ms = (time.monotonic() - cycle_start) * 1000
                kind = getattr(self._feed, "last_frame_kind", "odds")
                if kind == "heartbeat":
                    self._state["last_heartbeat_at"] = time.time()
                    self._state["frame_count"] += 1
                    if self._state.get("matches"):
                        self._state["last_update_at"] = time.time()
                        self._state["status"] = "running"
                        self._state["error"] = None
                        self._state["consecutive_failures"] = 0
                elif kind == "odds":
                    self._publish_success(matches, elapsed_ms)
                    backoff = INITIAL_BACKOFF_SECONDS
                else:
                    self._state["frame_count"] += 1
                self._maybe_log()
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._feed is not None and self._feed.has_catalogue():
                    print(
                        f"[ORBIT PREMATCH] socket dropped "
                        f"({type(exc).__name__}: {exc}); "
                        "reconnecting websocket with cached catalogue"
                    )
                    try:
                        await self._feed.reconnect_socket()
                        self._state["status"] = "running"
                        self._state["error"] = None
                        self._state["consecutive_failures"] = 0
                        backoff = INITIAL_BACKOFF_SECONDS
                        continue
                    except Exception as reconnect_exc:
                        print(
                            f"[ORBIT PREMATCH] socket reconnect failed "
                            f"({type(reconnect_exc).__name__}: {reconnect_exc}); "
                            "keeping catalogue and retrying"
                        )
                        self._state["status"] = "running"
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                        continue
                consecutive = self._publish_failure(exc)
                must_reconnect = (
                    connecting
                    or is_connection_dead_error(exc)
                    or consecutive >= MAX_INPLACE_RETRIES
                )
                if must_reconnect:
                    print(
                        f"[ORBIT PREMATCH] recovery needed "
                        f"({type(exc).__name__}: {exc}); retry in {backoff}s"
                    )
                    if self._feed is not None:
                        try:
                            await self._feed.close()
                        except Exception:
                            pass
                        self._feed = None
                    self._state["status"] = "reconnecting"
                    self._state["reconnect_count"] += 1
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                else:
                    print(
                        f"[ORBIT PREMATCH] transient error "
                        f"({type(exc).__name__}: {exc})"
                    )
                    await asyncio.sleep(INPLACE_RETRY_PAUSE_SECONDS)

    def _publish_success(self, _new_matches, elapsed_ms):
        state = self._state
        state["status"] = "running"
        state["error"] = None
        state["last_update_at"] = time.time()
        state["frame_count"] += 1
        state["success_count"] += 1
        state["consecutive_failures"] = 0
        state["consecutive_successes"] += 1
        state["last_processing_ms"] = elapsed_ms
        state["feed_healthy"] = True
        if self._feed is not None:
            all_matches = self._feed.get_match_odds()
            state["matches"] = all_matches
            state["back_count"] = self._feed.back_count
            state["lay_count"] = self._feed.lay_count
            state["last_event_count"] = len({
                (m.home_team, m.away_team) for m in all_matches
            })

    def _publish_failure(self, exc) -> int:
        state = self._state
        state["error"] = f"{type(exc).__name__}: {exc}"
        state["failed_count"] += 1
        state["consecutive_successes"] = 0
        state["consecutive_failures"] += 1
        return state["consecutive_failures"]

    async def _maybe_resubscribe(self):
        if self._feed is None:
            return
        last_odds = self._state.get("last_update_at")
        last_hb = self._state.get("last_heartbeat_at")
        if last_odds is None or last_hb is None:
            return
        if time.time() - last_odds < ODDS_STALE_WARN_SECONDS:
            return
        now = time.monotonic()
        if now - self._last_resubscribe_at < RESUBSCRIBE_COOLDOWN_SECONDS:
            return
        self._last_resubscribe_at = now
        try:
            n = await self._feed.resubscribe_all()
            print(f"[ORBIT PREMATCH] resubscribed {n} markets on existing session")
        except Exception as exc:
            print(f"[ORBIT PREMATCH] resubscribe failed ({type(exc).__name__}: {exc})")
            raise

    def _maybe_log(self):
        now = time.monotonic()
        if now - self._last_health_log_at < HEALTH_LOG_SECONDS:
            return
        self._last_health_log_at = now
        print(
            f"[ORBIT PREMATCH] frames received: {self._state.get('frame_count', 0)}"
        )
        print(
            f"[ORBIT PREMATCH] events parsed: {self._state.get('last_event_count', 0)}"
        )
        print(f"[ORBIT PREMATCH] back prices: {self._state.get('back_count', 0)}")
        print(f"[ORBIT PREMATCH] lay prices: {self._state.get('lay_count', 0)}")
        if self._feed is not None:
            stats = getattr(self._feed, "stats", {})
            print(
                "[PREMATCH][ORBIT] "
                f"REST={stats.get('rest_markets', 0)} "
                f"WS frames={stats.get('ws_frames', 0)} "
                f"WS odds={stats.get('ws_odds_frames', 0)} "
                f"unknown={stats.get('ws_unknown_market', 0)} "
                f"parse_rejected={stats.get('parse_rejected', 0)} "
                f"implied_rejected={stats.get('implied_rejected', 0)} "
                f"MatchOdds={stats.get('valid_matchodds', 0)}"
            )
        print("[ORBIT PREMATCH] state updated")
