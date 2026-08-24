"""Browser-context getMaclar fetch. No standalone HTTP client."""

from __future__ import annotations

import json

from parsers.kolay90_prematch.parser import is_unauthenticated

ENDPOINT = "https://kolay90.com/service/getMaclar"
UNAUTH_MARKER = "Lütfen Tekrar Giriş Yapınız"


def _fetch_via_context(page) -> dict | None:
    """Retry getMaclar with the Playwright context cookie jar."""
    request = getattr(page, "request", None)
    if request is None:
        return None
    try:
        response = request.get(
            ENDPOINT,
            headers={
                "accept": "application/json, text/plain, */*",
                "x-requested-with": "XMLHttpRequest",
            },
        )
        text = response.text()
        return {
            "status": response.status,
            "content_type": response.headers.get("content-type"),
            "bytes": len(text.encode("utf-8", errors="replace")),
            "text": text,
            "error": None,
            "latency_ms": None,
        }
    except Exception as exc:
        return {
            "status": None,
            "content_type": None,
            "bytes": 0,
            "text": "",
            "error": type(exc).__name__,
            "latency_ms": None,
        }


def fetch_getmaclar(page) -> dict:
    result = page.evaluate(
        """async (url) => {
            const started = Date.now();
            try {
                const response = await fetch(url, {
                    method: 'GET',
                    credentials: 'include',
                    headers: {
                        'accept': 'application/json, text/plain, */*',
                        'x-requested-with': 'XMLHttpRequest',
                    },
                    cache: 'no-store',
                });
                const text = await response.text();
                return {
                    status: response.status,
                    content_type: response.headers.get('content-type'),
                    bytes: new TextEncoder().encode(text).length,
                    text: text,
                    error: null,
                    latency_ms: Date.now() - started,
                };
            } catch (err) {
                return {
                    status: null,
                    content_type: null,
                    bytes: 0,
                    text: '',
                    error: String(err),
                    latency_ms: Date.now() - started,
                };
            }
        }""",
        ENDPOINT,
    )
    if result.get("status") in (401, 403):
        fallback = _fetch_via_context(page)
        if fallback is not None:
            result = fallback
    text = result.get("text") or ""
    payload = None
    json_ok = False
    if text.lstrip()[:1] in "{[":
        try:
            payload = json.loads(text)
            json_ok = True
        except json.JSONDecodeError:
            payload = None
    looks_html = "text/html" in (result.get("content_type") or "").lower() or text.lstrip()[:1] == "<"
    unauth = is_unauthenticated(payload) if json_ok else (
        UNAUTH_MARKER in text
    )
    return {
        "status": result.get("status"),
        "content_type": result.get("content_type"),
        "bytes": result.get("bytes") or 0,
        "json": json_ok,
        "payload": payload,
        "looks_html": looks_html,
        "unauthenticated": unauth,
        "error": result.get("error"),
        "latency_ms": result.get("latency_ms"),
        "cloudflare": bool(looks_html and result.get("status") in (403, 503, 200) and not json_ok),
    }
