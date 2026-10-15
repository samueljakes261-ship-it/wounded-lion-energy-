"""
Shared, dependency-light HTTP fetch helper for the Kenyan Bookmakers
module.

Uses `requests` (already a project dependency -- see requirements.txt)
rather than introducing a new HTTP library. Deliberately does NOT
touch adapters/zenrows_client.py, browser/*, or credentials/* -- those
remain exactly as they are for the existing Turkish/client-facing
bookmakers. If a Kenyan bookmaker ever needs an anti-bot-bypass session
(see kenyan/workers/sportpesa.py), it is expected to plug in via the
`session` parameter here rather than by modifying this module.
"""
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from kenyan.config import KENYAN_HTTP_TIMEOUT_SECONDS, KENYAN_USER_AGENT

_THREAD_SESSIONS = threading.local()


def _thread_session() -> requests.Session:
    session = getattr(_THREAD_SESSIONS, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_SESSIONS.session = session
    return session

DEFAULT_HEADERS = {
    "User-Agent": KENYAN_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
}


@dataclass
class FetchResult:
    """
    Everything a diagnostics record needs about one HTTP acquisition,
    kept separate from parsing so acquisition failures/anomalies (bot
    challenges, wrong content-type, HTTP errors) are always visible
    even when parsing never runs.
    """

    url: str
    ok: bool
    status_code: Optional[int]
    content_type: Optional[str]
    response_size_bytes: int
    elapsed_seconds: float
    json_body: Any = None
    text_body: str = ""
    error: Optional[str] = None
    pages_fetched: int = 1
    page_cap_hit: bool = False
    snapshot_complete: bool = True
    unique_event_ids: int = 0
    duplicate_events: int = 0
    source_total: Optional[int] = None
    terminal_reason: Optional[str] = None
    first_cursor: Optional[str] = None
    last_cursor: Optional[str] = None
    http_date: Optional[str] = None
    cache_age: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    cache_control: Optional[str] = None

    @property
    def looks_like_json(self) -> bool:
        return self.json_body is not None


def fetch_json(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = KENYAN_HTTP_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
    retries: int = 0,
) -> FetchResult:
    """
    Fetches `url` and attempts to decode it as JSON.

    Never raises for ordinary HTTP-layer problems (timeouts, non-200
    status, HTML instead of JSON e.g. an anti-bot challenge page) --
    those are all reported back via the returned FetchResult so a
    worker can record them as diagnostics/health rather than crashing.
    Only truly unexpected errors propagate.
    """

    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    attempts = max(0, int(retries)) + 1
    last_result = None
    for attempt in range(attempts):
        start = time.monotonic()
        client = session or _thread_session()
        try:
            response = client.get(url, headers=merged_headers, timeout=timeout)
        except requests.RequestException as exc:
            last_result = FetchResult(
                url=url,
                ok=False,
                status_code=None,
                content_type=None,
                response_size_bytes=0,
                elapsed_seconds=time.monotonic() - start,
                error=f"{type(exc).__name__}: {exc}",
            )
            if attempt + 1 < attempts:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
                continue
            return last_result

        elapsed = time.monotonic() - start
        content_type = response.headers.get("content-type")
        size = len(response.content or b"")
        cache_kwargs = dict(
            http_date=response.headers.get("date"),
            cache_age=response.headers.get("age"),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            cache_control=response.headers.get("cache-control"),
        )

        if response.status_code >= 400:
            last_result = FetchResult(
                url=url,
                ok=False,
                status_code=response.status_code,
                content_type=content_type,
                response_size_bytes=size,
                elapsed_seconds=elapsed,
                text_body=response.text[:2000],
                error=f"HTTP {response.status_code}",
                **cache_kwargs,
            )
            retryable = response.status_code >= 500 or response.status_code == 429
            if retryable and attempt + 1 < attempts:
                time.sleep(min(0.5 * (2 ** attempt), 2.0))
                continue
            return last_result

        json_body = None
        parse_error = None
        try:
            json_body = response.json()
        except ValueError as exc:
            parse_error = f"invalid JSON: {exc}"

        if json_body is None:
            return FetchResult(
                url=url,
                ok=False,
                status_code=response.status_code,
                content_type=content_type,
                response_size_bytes=size,
                elapsed_seconds=elapsed,
                text_body=response.text[:2000],
                error=parse_error or "empty/non-JSON response body",
                **cache_kwargs,
            )

        return FetchResult(
            url=url,
            ok=True,
            status_code=response.status_code,
            content_type=content_type,
            response_size_bytes=size,
            elapsed_seconds=elapsed,
            json_body=json_body,
            **cache_kwargs,
        )

    return last_result


def copy_cache_headers(target, fetch_result):
    """Copy HTTP cache/date headers onto Diagnostics or FetchResult."""
    if fetch_result is None:
        return target
    for name in ("http_date", "cache_age", "etag", "last_modified", "cache_control"):
        if hasattr(target, name):
            setattr(target, name, getattr(fetch_result, name, None))
    return target


WALK_FIELDS = (
    "pages_fetched",
    "page_cap_hit",
    "snapshot_complete",
    "unique_event_ids",
    "duplicate_events",
    "source_total",
    "terminal_reason",
    "first_cursor",
    "last_cursor",
)


def copy_walk_fields(target, fetch_result):
    """Copy catalogue-walk metadata onto Diagnostics or FetchResult."""
    if fetch_result is None:
        return target
    for name in WALK_FIELDS:
        if hasattr(target, name) and hasattr(fetch_result, name):
            setattr(target, name, getattr(fetch_result, name))
    return target


def looks_like_bot_challenge(fetch_result: FetchResult) -> bool:
    """
    Best-effort detection of an anti-bot / JS-challenge page returned
    instead of the real API payload (observed live on SportPesa --
    see kenyan/workers/sportpesa.py). Used only to produce an accurate
    diagnostics message/health reason; never used to fabricate success.
    """

    if fetch_result.looks_like_json:
        return False

    body = (fetch_result.text_body or "").lower()
    markers = (
        "challenge validation",
        "sec-cpt-if",
        "captcha",
        "cf-challenge",
        "just a moment",
        "attention required",
    )
    return any(marker in body for marker in markers)
