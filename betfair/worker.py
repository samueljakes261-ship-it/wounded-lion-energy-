"""
Persistent Betfair valuebets worker.

Polls GET https://verigood.top/valuebets every 3 seconds on its own
background thread. A failed poll never raises into the engine loop.
The latest successful parse is the current snapshot: items the source
stops returning disappear immediately.
"""
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from betfair.auth import (
    AuthError,
    ValuebetsAuth,
    configured_cookie,
    configured_static_token,
)
from betfair.config import (
    CACHE_FILE,
    HTTP_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    SOURCE_LABEL,
    STALE_AFTER_SECONDS,
    VALUEBETS_URL,
)
from betfair.health import HealthState, WorkerHealth
from betfair.http import FetchResult, auth_headers, fetch_json, optional_cookie_header
from betfair.models import LIVE, PREMATCH, UNKNOWN, BetfairOpportunity
from betfair.parser import parse_payload
from betfair.serialize import serialize_snapshot


@dataclass
class Diagnostics:
    endpoint_status: str = "unknown"
    http_status_code: Optional[int] = None
    response_size_bytes: int = 0
    elapsed_seconds: float = 0.0
    raw_count: int = 0
    valid_count: int = 0
    rejected_count: int = 0
    live_count: int = 0
    prematch_count: int = 0
    unknown_count: int = 0
    parser_error: Optional[str] = None


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _token() -> Optional[str]:
    return os.getenv("BETFAIR_VALUEBETS_TOKEN") or os.getenv("VALUEBETS_TOKEN") or None


def _result_to_diagnostics(result: FetchResult) -> Diagnostics:
    return Diagnostics(
        http_status_code=result.status_code,
        response_size_bytes=result.response_size_bytes,
        elapsed_seconds=result.elapsed_seconds,
    )


def _apply_parse(result: FetchResult) -> tuple[list[BetfairOpportunity], Diagnostics]:
    diagnostics = _result_to_diagnostics(result)

    if not result.ok:
        diagnostics.endpoint_status = (
            "invalid_json" if result.error and "invalid JSON" in result.error else "http_error"
        )
        diagnostics.parser_error = result.error
        return [], diagnostics

    parsed = parse_payload(result.json_body)
    diagnostics.raw_count = parsed.raw_count
    diagnostics.rejected_count = parsed.rejected
    diagnostics.valid_count = len(parsed.opportunities)
    diagnostics.live_count = parsed.live_count
    diagnostics.prematch_count = parsed.prematch_count
    diagnostics.unknown_count = parsed.unknown_count

    if parsed.error:
        diagnostics.endpoint_status = "bad_payload"
        diagnostics.parser_error = parsed.error
        return [], diagnostics

    diagnostics.endpoint_status = "ok"
    return parsed.opportunities, diagnostics


def acquire_once(
    *,
    url: str = VALUEBETS_URL,
    fetch_fn: Optional[Callable[..., FetchResult]] = None,
    auth: Optional[ValuebetsAuth] = None,
) -> tuple[list[BetfairOpportunity], Diagnostics]:
    fetcher = fetch_fn or fetch_json
    session = auth.session if auth is not None else None

    try:
        headers = auth.headers() if auth is not None else None
    except AuthError as exc:
        return [], Diagnostics(
            endpoint_status="auth_error",
            parser_error=str(exc),
        )

    if headers is None:
        headers = dict(auth_headers(configured_static_token() or _token()))
        headers.update(optional_cookie_header(configured_cookie()))

    result = fetcher(
        url,
        headers=headers,
        timeout=HTTP_TIMEOUT_SECONDS,
        session=session,
    )

    if result.status_code == 401 and auth is not None:
        auth.invalidate()
        try:
            headers = auth.headers()
        except AuthError as exc:
            return [], Diagnostics(
                endpoint_status="auth_error",
                http_status_code=401,
                parser_error=str(exc),
            )
        print("[BETFAIR] token rejected, re-login")
        result = fetcher(
            url,
            headers=headers,
            timeout=HTTP_TIMEOUT_SECONDS,
            session=session,
        )

    return _apply_parse(result)


def _log_cycle(diagnostics: Diagnostics) -> None:
    extra = (
        f"error={diagnostics.parser_error}"
        if diagnostics.parser_error
        else (
            f"records={diagnostics.raw_count} valid={diagnostics.valid_count} "
            f"rejected={diagnostics.rejected_count} live={diagnostics.live_count} "
            f"prematch={diagnostics.prematch_count} unknown={diagnostics.unknown_count}"
        )
    )
    print(
        f"[BETFAIR] status_code={diagnostics.http_status_code} "
        f"elapsed_ms={int(diagnostics.elapsed_seconds * 1000)} "
        f"payload_bytes={diagnostics.response_size_bytes} {extra}"
    )


class BetfairValuebetsWorker:
    def __init__(
        self,
        *,
        poll_fn: Optional[Callable[[], tuple[list[BetfairOpportunity], Diagnostics]]] = None,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        cache_file: Optional[Path] = None,
        fetch_fn: Optional[Callable[..., FetchResult]] = None,
        auth: Optional[ValuebetsAuth] = None,
    ):
        self.name = SOURCE_LABEL
        self._poll_interval_seconds = poll_interval_seconds
        self._cache_file = cache_file or CACHE_FILE
        self._fetch_fn = fetch_fn
        self._auth = auth or ValuebetsAuth()
        self._poll_fn = poll_fn or self._default_poll

        self._lock = threading.Lock()
        self._opportunities: list[BetfairOpportunity] = []
        self._last_good_at: Optional[float] = None
        self._last_attempt_at: Optional[float] = None
        self._last_diagnostics: Optional[Diagnostics] = None
        self._health_state = HealthState()
        self._poll_count = 0
        self._success_count = 0
        self._failed_count = 0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _default_poll(self) -> tuple[list[BetfairOpportunity], Diagnostics]:
        return acquire_once(fetch_fn=self._fetch_fn, auth=self._auth)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="betfair-valuebets-worker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            self._run_one_cycle()
            elapsed = time.monotonic() - cycle_start
            self._stop_event.wait(max(0.0, self._poll_interval_seconds - elapsed))

    def _run_one_cycle(self):
        now = time.time()
        self._poll_count += 1
        try:
            opportunities, diagnostics = self._poll_fn()
        except Exception as exc:  # noqa: BLE001 -- worker must never die
            diagnostics = Diagnostics(
                endpoint_status="exception",
                parser_error=f"{type(exc).__name__}: {exc}",
            )
            opportunities = []
            with self._lock:
                self._last_attempt_at = now
                self._last_diagnostics = diagnostics
                self._failed_count += 1
                self._health_state.record_failure(diagnostics.parser_error)
            _log_cycle(diagnostics)
            return

        _log_cycle(diagnostics)

        with self._lock:
            self._last_attempt_at = now
            self._last_diagnostics = diagnostics
            usable = (
                diagnostics.endpoint_status == "ok" and diagnostics.parser_error is None
            )
            if usable:
                self._opportunities = list(opportunities)
                self._last_good_at = now
                self._success_count += 1
                self._health_state.record_success()
                self._write_snapshot_unlocked()
            else:
                self._failed_count += 1
                self._health_state.record_failure(
                    diagnostics.parser_error
                    or f"endpoint_status={diagnostics.endpoint_status}"
                )

    def _write_snapshot_unlocked(self) -> None:
        if self._last_good_at is None:
            return
        payload = serialize_snapshot(
            self._opportunities,
            last_success_at=self._last_good_at,
            rejected=(
                self._last_diagnostics.rejected_count if self._last_diagnostics else 0
            ),
        )
        try:
            _atomic_write_text(
                self._cache_file,
                json.dumps(payload, indent=2, ensure_ascii=False),
            )
        except OSError as exc:
            print(f"[BETFAIR] Failed to write cache ({type(exc).__name__}: {exc})")

    def get_opportunities(self) -> list[BetfairOpportunity]:
        with self._lock:
            if self._last_good_at is None:
                return []
            if (time.time() - self._last_good_at) > STALE_AFTER_SECONDS:
                return []
            return list(self._opportunities)

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            health = self._health_state.classify(
                last_good_at=self._last_good_at, now=now
            )
            age = (now - self._last_good_at) if self._last_good_at else None
            diagnostics = self._last_diagnostics
            live_count = sum(
                1 for item in self._opportunities if item.live_classification == LIVE
            )
            prematch_count = sum(
                1
                for item in self._opportunities
                if item.live_classification == PREMATCH
            )
            unknown_count = sum(
                1
                for item in self._opportunities
                if item.live_classification == UNKNOWN
            )
            if not self.is_alive():
                raw_status = (
                    "stopped"
                    if self._stop_event.is_set() or self._thread is None
                    else "error"
                )
            elif health is WorkerHealth.STARTING:
                raw_status = "starting"
            else:
                raw_status = "running"

            avg_ms = None
            if diagnostics is not None:
                avg_ms = round(diagnostics.elapsed_seconds * 1000, 1)

            return {
                "name": self.name,
                "status": raw_status,
                "health": health.value,
                "error": self._health_state.last_error,
                "last_update_at": self._last_good_at,
                "last_attempt_at": self._last_attempt_at,
                "consecutive_failures": self._health_state.consecutive_failures,
                "consecutive_successes": self._health_state.consecutive_successes,
                "reconnect_count": 0,
                "event_count": len(self._opportunities) if self._last_good_at else 0,
                "live_records": live_count,
                "prematch_records": prematch_count,
                "unknown_records": unknown_count,
                "poll_interval": self._poll_interval_seconds,
                "poll_count": self._poll_count,
                "success_count": self._success_count,
                "failed_count": self._failed_count,
                "avg_processing_ms": avg_ms,
                "age_seconds": age,
            }
