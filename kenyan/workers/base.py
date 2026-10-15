"""
Base persistent worker for the Kenyan Bookmakers module.

Architecture (per the task's explicit requirement):

    worker starts
        -> initial acquisition
        -> parse payload
        -> update bookmaker snapshot
        -> wait 5 seconds
        -> poll again
        -> parse
        -> update snapshot
        -> repeat indefinitely

One persistent background thread per (bookmaker, LIVE/PREMATCH) feed --
never a new process/browser per poll. A plain `threading.Thread` is
sufficient here (unlike OnWin, which needs a separate process for its
Playwright sync API -- see collector.py) because every Kenyan
acquisition in this module is a simple stateless HTTP GET (`requests`),
not a long-lived browser session.

Last-good snapshot behavior: a failed or empty poll never immediately
blanks out previously-published valid opportunities. The most recent
successful (non-empty OR explicitly-confirmed-empty) result keeps being
served by `get_matches()` until it exceeds KENYAN_STALE_AFTER_SECONDS,
matching the project's own general stale-data policy (see
collector.py's MAX_ODDS_AGE_SECONDS) but as an independent constant so
nothing here can affect the existing bookmakers' staleness handling.
"""
import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from kenyan.config import KENYAN_POLL_INTERVAL_SECONDS, KENYAN_STALE_AFTER_SECONDS
from kenyan.health import HealthState, WorkerHealth
from kenyan.match_snapshot import merge_match_records, visible_matches
from kenyan.metrics import log_cycle


@dataclass
class Diagnostics:
    """
    Isolated diagnostics record for one acquisition cycle -- see the
    task's "DIAGNOSTICS" requirement. Deliberately excludes anything
    resembling a credential/session token; these workers are plain
    unauthenticated HTTP GETs, so there is nothing sensitive to redact,
    but the shape is kept minimal on principle regardless.
    """

    endpoint_status: str = "unknown"  # "ok" | "http_error" | "bad_payload" | "exception"
    http_status_code: Optional[int] = None
    content_type: Optional[str] = None
    response_size_bytes: int = 0
    events_discovered: int = 0
    football_events: int = 0
    one_x_two_events: int = 0
    valid_normalized_events: int = 0
    parser_error: Optional[str] = None
    acquired_at: Optional[float] = None
    elapsed_seconds: float = 0.0
    pages_fetched: int = 0
    page_cap_hit: bool = False
    snapshot_complete: bool = True
    catalogue_status: str = "unknown"
    source_total: Optional[int] = None
    unique_event_ids: int = 0
    duplicate_events: int = 0
    terminal_reason: Optional[str] = None
    first_cursor: Optional[str] = None
    last_cursor: Optional[str] = None
    http_date: Optional[str] = None
    cache_age: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    cache_control: Optional[str] = None


def derive_catalogue_status(diagnostics: "Diagnostics") -> str:
    """
    complete / partial / failed / empty_complete from acquisition
    evidence. A page cap or incomplete walk is never reported complete.
    """
    failed = diagnostics.endpoint_status not in ("ok",) or bool(diagnostics.parser_error)
    discovered = diagnostics.events_discovered or diagnostics.valid_normalized_events
    if failed and not discovered:
        return "failed"
    if diagnostics.page_cap_hit or not diagnostics.snapshot_complete:
        return "partial"
    if failed:
        return "partial"
    if not discovered:
        return "empty_complete"
    return "complete"


def apply_catalogue_status(diagnostics: "Diagnostics") -> "Diagnostics":
    diagnostics.catalogue_status = derive_catalogue_status(diagnostics)
    return diagnostics


class BaseKenyanWorker:
    """
    `poll_fn` is a zero-argument callable that performs ONE full
    acquire -> parse -> normalize cycle and returns
    `(matches: list[KenyanMatchOdds], diagnostics: Diagnostics)`.
    It must not raise for ordinary, expected failure modes (HTTP
    errors, bad payloads) -- those should be reflected in the returned
    Diagnostics instead, so a single bad cycle degrades health rather
    than killing the worker thread. Only a truly unexpected exception
    should propagate, and even then this base class catches it so the
    thread itself never dies.
    """

    def __init__(
        self,
        name: str,
        poll_fn: Callable[[], "tuple"],
        *,
        poll_interval_seconds: float = KENYAN_POLL_INTERVAL_SECONDS,
        retention_seconds: Optional[float] = None,
    ):
        self.name = name
        self._poll_fn = poll_fn
        self._poll_interval_seconds = poll_interval_seconds
        self._retention_seconds = (
            KENYAN_STALE_AFTER_SECONDS if retention_seconds is None else retention_seconds
        )

        self._lock = threading.Lock()
        self._matches = []
        self._match_records = {}
        self._last_good_at: Optional[float] = None
        self._last_attempt_at: Optional[float] = None
        self._last_diagnostics: Optional[Diagnostics] = None
        self._health_state = HealthState()
        self._acquired_seq = 0

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._poll_in_flight = False
        self._on_snapshot = None
        self._content_fingerprint = None
        self._poll_count = 0

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"kenyan-{self.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_on_snapshot(self, callback):
        """Optional hook after a successful LIVE snapshot publish. PREMATCH leaves this unset."""
        self._on_snapshot = callback

    def content_fingerprint(self):
        with self._lock:
            return self._content_fingerprint

    def snapshot_meta(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "acquired_seq": self._acquired_seq,
                "poll_count": self._poll_count,
                "poll_in_flight": self._poll_in_flight,
                "last_good_at": self._last_good_at,
                "content_fingerprint": self._content_fingerprint,
            }

    # ------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------

    def _run(self):
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            self._run_one_cycle()
            elapsed = time.monotonic() - cycle_start
            self._stop_event.wait(max(0.0, self._poll_interval_seconds - elapsed))

    def _run_one_cycle(self):
        wall_start = time.monotonic()
        with self._lock:
            if self._poll_in_flight:
                log_cycle(
                    bookmaker=self.name,
                    mode="skipped",
                    stage="acquire",
                    skipped_overlap=1,
                    poll_count=self._poll_count,
                )
                return
            self._poll_in_flight = True
            self._poll_count += 1
            previous_fp = self._content_fingerprint
            previous_good = self._last_good_at
        try:
            matches, diagnostics = self._poll_fn()
        except Exception as exc:  # noqa: BLE001 -- worker must never die
            now = time.time()
            with self._lock:
                self._poll_in_flight = False
                self._last_attempt_at = now
                self._health_state.record_failure(f"{type(exc).__name__}: {exc}")
                self._last_diagnostics = apply_catalogue_status(
                    Diagnostics(
                        endpoint_status="exception",
                        parser_error=f"{type(exc).__name__}: {exc}",
                        acquired_at=now,
                        snapshot_complete=False,
                    )
                )
            log_cycle(
                bookmaker=self.name,
                mode="exception",
                stage="acquire",
                cycle_id=self._poll_count,
                cycle_ms=round((time.monotonic() - wall_start) * 1000, 1),
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        now = time.time()
        published = False
        odds_changed = None
        acquired_seq = 0
        payload_hash = None
        with self._lock:
            self._poll_in_flight = False
            self._last_attempt_at = now
            apply_catalogue_status(diagnostics)
            self._last_diagnostics = diagnostics

            if diagnostics.endpoint_status == "ok" and diagnostics.parser_error is None:
                self._acquired_seq += 1
                self._match_records = merge_match_records(
                    self._match_records,
                    matches,
                    now=now,
                    retention_seconds=self._retention_seconds,
                    acquired_seq=self._acquired_seq,
                    expire_unseen=bool(diagnostics.snapshot_complete),
                )
                self._matches = visible_matches(
                    self._match_records,
                    now=now,
                    retention_seconds=self._retention_seconds,
                )
                self._content_fingerprint = _matches_fingerprint(self._matches)
                published = True
                odds_changed = self._content_fingerprint != previous_fp
                payload_hash = _fingerprint_hash(self._content_fingerprint)
                if matches:
                    self._last_good_at = now
                    self._health_state.record_success()
                else:
                    # Well-formed payload, genuinely zero relevant
                    # events right now (e.g. no live football matches
                    # this instant) -- not a failure. Previously seen
                    # events stay until per-event retention expires.
                    self._health_state.record_empty_but_ok()
            else:
                self._health_state.record_failure(
                    diagnostics.parser_error or f"endpoint_status={diagnostics.endpoint_status}"
                )
            acquired_seq = self._acquired_seq
        if published and self._on_snapshot is not None:
            try:
                self._on_snapshot()
            except Exception:
                pass
        log_cycle(
            bookmaker=self.name,
            mode="ok" if diagnostics.endpoint_status == "ok" else diagnostics.endpoint_status,
            stage="acquire",
            cycle_id=self._poll_count,
            acquired_seq=acquired_seq,
            events=diagnostics.events_discovered,
            normalized=diagnostics.valid_normalized_events,
            bytes=diagnostics.response_size_bytes,
            elapsed=round(diagnostics.elapsed_seconds, 3),
            cycle_ms=round((time.monotonic() - wall_start) * 1000, 1),
            pages=diagnostics.pages_fetched,
            page_cap_hit=int(diagnostics.page_cap_hit),
            snapshot_complete=int(diagnostics.snapshot_complete),
            catalogue_status=diagnostics.catalogue_status,
            source_total=diagnostics.source_total,
            unique_events=diagnostics.unique_event_ids,
            duplicate_events=diagnostics.duplicate_events,
            terminal_reason=diagnostics.terminal_reason,
            first_cursor=diagnostics.first_cursor,
            last_cursor=diagnostics.last_cursor,
            odds_changed=None if odds_changed is None else int(odds_changed),
            payload_hash=payload_hash,
            since_last_good_s=(
                None if previous_good is None else round(now - previous_good, 3)
            ),
            http_status=diagnostics.http_status_code,
            http_date=diagnostics.http_date,
            cache_age=diagnostics.cache_age,
            etag=diagnostics.etag,
            last_modified=diagnostics.last_modified,
            cache_control=diagnostics.cache_control,
            next_wait_ms=round(
                max(0.0, self._poll_interval_seconds * 1000 - (time.monotonic() - wall_start) * 1000),
                1,
            ),
            error=diagnostics.parser_error or "",
        )

    # ------------------------------------------------------------
    # Readers (safe to call from any thread, cheap, no network/IO)
    # ------------------------------------------------------------

    def get_matches(self) -> list:
        """
        Last-good *per-event* snapshot. A successful poll that returns
        only a subset of previously seen events (LIVE pages are count-
        limited) merges into the existing records instead of replacing
        them. Individual events expire after KENYAN_STALE_AFTER_SECONDS
        without being seen, matching the project's Kenyan stale-data
        policy. Failed polls do not mark events absent.
        """

        with self._lock:
            now = time.time()
            if not self._match_records:
                return []
            if self._poll_in_flight and self._last_good_at is not None:
                now = self._last_good_at
            # Do not restamp collected_at here. LIVE merge preserves
            # the price-change time; confirmed_at/last_seen track the
            # last poll that still contained these odds.
            return visible_matches(
                self._match_records,
                now=now,
                retention_seconds=self._retention_seconds,
            )

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            if self._poll_in_flight and self._last_good_at is not None:
                now = self._last_good_at
            health = self._health_state.classify(last_good_at=self._last_good_at, now=now)
            age = (now - self._last_good_at) if self._last_good_at else None

            return {
                "name": self.name,
                "health": health.value,
                "last_good_at": self._last_good_at,
                "last_attempt_at": self._last_attempt_at,
                "age_seconds": age,
                "match_count": len(
                    visible_matches(
                        self._match_records,
                        now=now,
                        retention_seconds=self._retention_seconds,
                    )
                ),
                "acquired_seq": self._acquired_seq,
                "poll_count": self._poll_count,
                "poll_in_flight": self._poll_in_flight,
                "error": self._health_state.last_error,
                "diagnostics": _diagnostics_to_dict(self._last_diagnostics),
            }


def _fingerprint_hash(fingerprint) -> str:
    if not fingerprint:
        return ""
    digest = hashlib.sha1(repr(fingerprint).encode("utf-8")).hexdigest()
    return digest[:12]


def _matches_fingerprint(matches) -> tuple:
    rows = []
    for match in matches or []:
        rows.append(
            (
                getattr(match, "bookmaker", ""),
                getattr(match, "event_id", ""),
                getattr(match, "market", ""),
                getattr(match, "period", ""),
                getattr(match, "line", None),
                getattr(match, "home_odds", None),
                getattr(match, "draw_odds", None),
                getattr(match, "away_odds", None),
            )
        )
    rows.sort()
    return tuple(rows)


def _diagnostics_to_dict(diagnostics: Optional[Diagnostics]) -> Optional[dict]:
    if diagnostics is None:
        return None
    return {
        "endpoint_status": diagnostics.endpoint_status,
        "http_status_code": diagnostics.http_status_code,
        "content_type": diagnostics.content_type,
        "response_size_bytes": diagnostics.response_size_bytes,
        "events_discovered": diagnostics.events_discovered,
        "football_events": diagnostics.football_events,
        "one_x_two_events": diagnostics.one_x_two_events,
        "valid_normalized_events": diagnostics.valid_normalized_events,
        "parser_error": diagnostics.parser_error,
        "acquired_at": diagnostics.acquired_at,
        "elapsed_seconds": diagnostics.elapsed_seconds,
        "pages_fetched": diagnostics.pages_fetched,
        "page_cap_hit": diagnostics.page_cap_hit,
        "snapshot_complete": diagnostics.snapshot_complete,
        "catalogue_status": diagnostics.catalogue_status,
        "source_total": diagnostics.source_total,
        "unique_event_ids": diagnostics.unique_event_ids,
        "duplicate_events": diagnostics.duplicate_events,
        "terminal_reason": diagnostics.terminal_reason,
        "first_cursor": diagnostics.first_cursor,
        "last_cursor": diagnostics.last_cursor,
        "http_date": diagnostics.http_date,
        "cache_age": diagnostics.cache_age,
        "etag": diagnostics.etag,
        "last_modified": diagnostics.last_modified,
        "cache_control": diagnostics.cache_control,
    }
