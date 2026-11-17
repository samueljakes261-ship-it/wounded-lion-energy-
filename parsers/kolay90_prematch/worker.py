"""Persistent Kolay90 prematch worker.

Attaches once to the operator's authenticated Chrome and reuses that
page for every getMaclar poll. Does not launch or close Chrome.
"""

from __future__ import annotations

import os
import threading
import time

from parsers.kolay90_prematch.auth_phase import (
    AUTHENTICATED,
    derive_auth_phase,
    update_session_record,
)
from parsers.kolay90_prematch.feed import Kolay90PrematchFeed
from parsers.kolay90_prematch.session_state import AUTH_REQUIRED

POLL_INTERVAL = float(os.getenv("KOLAY90_PREMATCH_POLL_INTERVAL", "90"))
AUTH_WAIT_SECONDS = 60.0


class Kolay90PrematchWorker:
    def __init__(self, poll_interval=POLL_INTERVAL, feed=None):
        self.poll_interval = poll_interval
        self._feed = feed
        self._owns_feed = feed is None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._state = {
            "matches": [],
            "status": "starting",
            "error": None,
            "last_update_at": None,
            "last_attempt_at": None,
            "poll_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "reconnect_count": 0,
            "last_processing_ms": None,
            "avg_processing_ms": None,
            "last_event_count": 0,
            "last_odds_count": 0,
            "auth_state": None,
            "auth_phase": "NOT_INITIALIZED",
            "authenticated": False,
            "manual_intervention_required": False,
            "last_authenticated_at": None,
            "last_authenticated_request_at": None,
            "last_auth_error": None,
        }

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        print("[KOLAY90 PREMATCH] STARTING — attaching to existing Chrome")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kolay90-prematch-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=15):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        with self._lock:
            self._state["status"] = "stopped"

    def get_matches(self):
        with self._lock:
            return list(self._state["matches"])

    def get_status(self):
        with self._lock:
            return dict(self._state)

    def _run(self):
        from engine.sync_playwright_thread import isolate_from_running_asyncio_loop

        isolate_from_running_asyncio_loop()
        try:
            self._run_loop()
        except Exception as exc:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[KOLAY90 PREMATCH] worker crashed ({type(exc).__name__}: {exc})")
        finally:
            self._close_feed()

    def _close_feed(self):
        if not self._owns_feed:
            return
        feed = self._feed
        self._feed = None
        if feed is None:
            return
        try:
            feed.close()
        except Exception:
            pass

    def _prepare_vnc_desktop(self):
        flag = (os.getenv("KOLAY90_VNC_AUTOSTART") or "").strip().lower()
        if flag not in {"1", "true", "yes"}:
            return
        from parsers.kolay90_prematch.vnc_session import ensure_desktop

        result = ensure_desktop(autostart=True)
        print(
            "[KOLAY90 PREMATCH] RealVNC desktop "
            f"display={result.get('display')} "
            f"vnc_listening={str(bool(result.get('vnc_listening'))).lower()} "
            f"cdp_listening={str(bool(result.get('cdp_listening'))).lower()} "
            f"ok={str(bool(result.get('ok'))).lower()} "
            f"failure={result.get('failure') or '-'}"
        )

    def _run_loop(self):
        self._prepare_vnc_desktop()
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            with self._lock:
                self._state["last_attempt_at"] = time.time()
            try:
                if self._feed is None:
                    with self._lock:
                        self._state["status"] = "connecting"
                    self._feed = Kolay90PrematchFeed()
                result = self._feed.poll()
                elapsed_ms = (time.monotonic() - cycle_start) * 1000
                wait = self.poll_interval
                needs_operator = (
                    result.get("auth_required")
                    or result.get("auth_state") == AUTH_REQUIRED
                    or result.get("failure")
                    in {"cdp_attach_failed", "browser_page_closed", "kolay90_tab_missing"}
                )
                if needs_operator:
                    from parsers.kolay90_prematch.vnc_session import (
                        desktop_status,
                        operator_message,
                        recover_crashed_chrome,
                    )

                    desktop = desktop_status()
                    if (
                        result.get("failure")
                        in {"cdp_attach_failed", "browser_page_closed", "kolay90_tab_missing"}
                        and not desktop.get("cdp_listening")
                    ):
                        desktop = recover_crashed_chrome(desktop)
                    result["session_desktop"] = desktop
                    if result.get("auth_required") or result.get("auth_state") == AUTH_REQUIRED:
                        wait = AUTH_WAIT_SECONDS
                        print("[KOLAY90 PREMATCH] KOLAY90_AUTHENTICATION_REQUIRED")
                        print(
                            "[KOLAY90 PREMATCH] "
                            + operator_message(result.get("failure"), desktop)
                        )
                self._publish(result, elapsed_ms)
                remaining = max(0.0, wait - (elapsed_ms / 1000.0))
                if self._stop_event.wait(timeout=remaining):
                    break
            except Exception as exc:
                self._publish_failure(exc)
                print(f"[KOLAY90 PREMATCH] cycle failed ({type(exc).__name__}: {exc})")
                if self._stop_event.wait(timeout=min(self.poll_interval, 30.0)):
                    break

    def _publish(self, result: dict, elapsed_ms: float) -> None:
        matches = list(result.get("matches") or [])
        auth_required = bool(result.get("auth_required"))
        with self._lock:
            state = self._state
            desktop = result.get("session_desktop") or {}
            previous = state.get("auth_phase")
            phase = derive_auth_phase(
                browser_listening=bool(desktop.get("cdp_listening")),
                page_state=result.get("session_state") or result.get("auth_state"),
                fetch_authenticated=bool(result.get("ok") and result.get("authenticated")),
                fetch_failure=None if result.get("ok") else result.get("failure"),
                previously_authenticated=(
                    previous == AUTHENTICATED or bool(state.get("last_authenticated_at"))
                ),
            )
            state["poll_count"] += 1
            state["last_processing_ms"] = elapsed_ms
            state["auth_state"] = result.get("auth_state")
            state["auth_phase"] = phase
            state["authenticated"] = phase == AUTHENTICATED
            state["manual_intervention_required"] = phase in {
                "AWAITING_MANUAL_AUTH",
                "SESSION_EXPIRED",
                "AUTHENTICATION_FAILED",
            }
            if result.get("session_desktop") is not None:
                state["session_desktop"] = {
                    "display": desktop.get("display"),
                    "vnc_port": desktop.get("vnc_port"),
                    "vnc_listening": desktop.get("vnc_listening"),
                    "cdp_listening": desktop.get("cdp_listening"),
                    "browser_process": desktop.get("browser_process"),
                    "chrome_profile": desktop.get("chrome_profile"),
                    "auth_phase": phase,
                }
            if result.get("ok"):
                state["matches"] = matches
                state["last_event_count"] = result.get("total_events") or len(matches)
                state["last_odds_count"] = result.get("one_x_two") or len(matches)
                state["status"] = "running"
                state["error"] = None
                state["last_auth_error"] = None
                state["last_update_at"] = time.time()
                state["success_count"] += 1
                state["consecutive_failures"] = 0
                state["consecutive_successes"] += 1
                n = state["success_count"]
                prev = state["avg_processing_ms"]
                state["avg_processing_ms"] = (
                    elapsed_ms if prev is None else prev + (elapsed_ms - prev) / n
                )
            else:
                if not state["matches"] and matches:
                    state["matches"] = matches
                state["failed_count"] += 1
                state["consecutive_successes"] = 0
                state["consecutive_failures"] += 1
                state["error"] = result.get("failure")
                state["last_auth_error"] = result.get("failure")
                if auth_required or phase in {"AWAITING_MANUAL_AUTH", "SESSION_EXPIRED"}:
                    state["status"] = "authentication_required"
                elif phase == "AUTHENTICATION_FAILED" and not state.get("matches"):
                    state["status"] = "error"
                elif state.get("matches"):
                    state["status"] = "degraded"
                else:
                    state["status"] = "error"
            try:
                saved = update_session_record(
                    phase=phase,
                    error=None if result.get("ok") else result.get("failure"),
                    profile=desktop.get("chrome_profile"),
                    browser_process=desktop.get("browser_process"),
                    authenticated_request=bool(result.get("ok") and result.get("authenticated")),
                )
                state["last_authenticated_at"] = saved.get("last_authenticated_at")
                state["last_authenticated_request_at"] = saved.get(
                    "last_authenticated_request_at"
                )
            except OSError:
                pass
        print(
            f"[KOLAY90 PREMATCH] status={result.get('status')} "
            f"events={result.get('total_events')} "
            f"valid_football_1x2={result.get('one_x_two')} "
            f"session={result.get('auth_state')} "
            f"phase={phase} "
            f"authenticated={str(phase == AUTHENTICATED).lower()} "
            f"kept_last_good={result.get('kept_last_good')}"
        )

    def _publish_failure(self, exc) -> None:
        with self._lock:
            state = self._state
            state["error"] = f"{type(exc).__name__}: {exc}"
            state["poll_count"] += 1
            state["failed_count"] += 1
            state["consecutive_successes"] = 0
            state["consecutive_failures"] += 1
            if state.get("matches"):
                state["status"] = "degraded"
