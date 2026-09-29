"""Plain HTTP GET helper for the Betfair valuebets endpoint. No browser/ZenRows."""
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from betfair.config import HTTP_TIMEOUT_SECONDS, USER_AGENT, VALUEBETS_URL

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
}


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


def auth_headers(token: Optional[str]) -> dict[str, str]:
    """Attach a Bearer token if present. Never logs the value."""
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "token": token,
    }


def optional_cookie_header(cookie: Optional[str]) -> dict[str, str]:
    """Attach an operator-supplied Cookie header. Never logs the value."""
    if not cookie:
        return {}
    return {"Cookie": cookie}


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
    client = session or requests

    try:
        response = client.get(url, headers=merged_headers, timeout=timeout)
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

    if response.status_code < 200 or response.status_code >= 300:
        return FetchResult(
            url=url,
            ok=False,
            status_code=response.status_code,
            content_type=content_type,
            response_size_bytes=size,
            elapsed_seconds=elapsed,
            error=f"HTTP {response.status_code}",
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
        )

    return FetchResult(
        url=url,
        ok=True,
        status_code=response.status_code,
        content_type=content_type,
        response_size_bytes=size,
        elapsed_seconds=elapsed,
        json_body=json_body,
    )
