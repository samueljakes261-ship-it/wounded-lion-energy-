"""Plain HTTP GET helper for the Betfair valuebets endpoint. No browser/ZenRows."""
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from betfair.config import HTTP_TIMEOUT_SECONDS, USER_AGENT, VALUEBETS_URL

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

# Phrases observed on Verigood 401 bodies, plus unambiguous English
# equivalents. Used only to classify 403 — never logged.
_AUTH_FAILURE_MARKERS = (
    "token gerekli",
    "token required",
    "invalid token",
    "expired token",
    "not authenticated",
    "unauthorized",
)


@dataclass
class FetchResult:
    url: str
    ok: bool
    status_code: Optional[int]
    content_type: Optional[str]
    response_size_bytes: int
    elapsed_seconds: float
    json_body: Any = None
    error: Optional[str] = None
    is_auth_failure: bool = False
    redirect_location: Optional[str] = None


def auth_headers(token: Optional[str]) -> dict[str, str]:
    """Attach HTTPBearer as documented by the Verigood OpenAPI spec."""
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _safe_body_preview(content: bytes, limit: int = 200) -> str:
    """Decode a short prefix for classification. Caller must not log it."""
    if not content:
        return ""
    return content[:limit].decode("utf-8", errors="replace")


def classify_auth_failure(
    *,
    status_code: Optional[int],
    content_type: Optional[str] = None,
    location: Optional[str] = None,
    body_preview: str = "",
) -> bool:
    """
    Decide whether a response is an authentication failure.

    HTTP 401 is always authentication.
    HTTP 403 is authentication only when the body clearly says so.
    A redirect is authentication only when Location points at login/auth.
    """
    if status_code == 401:
        return True

    if status_code is not None and 300 <= status_code < 400:
        loc = (location or "").lower()
        return "login" in loc or "/auth" in loc

    if status_code == 403:
        text = body_preview.lower()
        return any(marker in text for marker in _AUTH_FAILURE_MARKERS)

    return False


def _is_html(content_type: Optional[str]) -> bool:
    if not content_type:
        return False
    return "html" in content_type.lower()


def fetch_json(
    url: str = VALUEBETS_URL,
    *,
    headers: Optional[dict] = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> FetchResult:
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    start = time.monotonic()
    client = session if session is not None else requests

    try:
        response = client.get(
            url,
            headers=merged_headers,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return FetchResult(
            url=url,
            ok=False,
            status_code=None,
            content_type=None,
            response_size_bytes=0,
            elapsed_seconds=time.monotonic() - start,
            error=f"{type(exc).__name__}: {exc}",
        )

    elapsed = time.monotonic() - start
    content_type = response.headers.get("content-type")
    size = len(response.content or b"")
    location = response.headers.get("location")
    body_preview = _safe_body_preview(response.content or b"")
    auth_failure = classify_auth_failure(
        status_code=response.status_code,
        content_type=content_type,
        location=location,
        body_preview=body_preview,
    )

    if response.status_code < 200 or response.status_code >= 300:
        return FetchResult(
            url=url,
            ok=False,
            status_code=response.status_code,
            content_type=content_type,
            response_size_bytes=size,
            elapsed_seconds=elapsed,
            error=f"HTTP {response.status_code}",
            is_auth_failure=auth_failure,
            redirect_location=location,
        )

    if _is_html(content_type):
        return FetchResult(
            url=url,
            ok=False,
            status_code=response.status_code,
            content_type=content_type,
            response_size_bytes=size,
            elapsed_seconds=elapsed,
            error="HTML response (not JSON)",
            is_auth_failure=auth_failure,
            redirect_location=location,
        )

    try:
        json_body = response.json()
    except ValueError as exc:
        return FetchResult(
            url=url,
            ok=False,
            status_code=response.status_code,
            content_type=content_type,
            response_size_bytes=size,
            elapsed_seconds=elapsed,
            error=f"invalid JSON: {exc}",
            is_auth_failure=auth_failure,
            redirect_location=location,
        )

    return FetchResult(
        url=url,
        ok=True,
        status_code=response.status_code,
        content_type=content_type,
        response_size_bytes=size,
        elapsed_seconds=elapsed,
        json_body=json_body,
        is_auth_failure=False,
        redirect_location=location,
    )
