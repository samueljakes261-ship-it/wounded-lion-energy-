"""Browser-context getMaclar fetch. No standalone HTTP client."""

from __future__ import annotations

import json

from parsers.kolay90_prematch.parser import is_unauthenticated

ENDPOINT = "https://kolay90.com/service/getMaclar"
UNAUTH_MARKER = "Lütfen Tekrar Giriş Yapınız"


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
