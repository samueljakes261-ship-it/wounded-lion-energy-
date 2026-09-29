"""Orbit HTTP/WebSocket access classification.

Never stores or formats cookies, CSRF tokens, or Authorization
headers. Status codes and exception *types* are enough to tell a
datacenter/session rejection apart from a parser bug.
"""


class OrbitAccessError(Exception):
    """REST/WebSocket rejected before usable market data arrived."""

    def __init__(self, category: str, http_status: int | None, detail: str):
        self.category = category
        self.http_status = http_status
        super().__init__(
            f"Orbit access {category} status={http_status} ({detail})"
        )


def classify_http_status(status: int) -> str:
    if status in (401, 403):
        return "auth_or_access_denied"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "redirect"
    if 500 <= status < 600:
        return "server_error"
    if status == 200:
        return "ok"
    return "http_error"


def classify_response_body_kind(content_type: str | None, body_prefix: str) -> str:
    ctype = (content_type or "").lower()
    prefix = (body_prefix or "").lstrip().lower()
    if "json" in ctype or prefix.startswith("{") or prefix.startswith("["):
        return "json"
    if "cloudflare" in prefix or "cf-browser-verification" in prefix:
        return "cdn_challenge"
    if prefix.startswith("<!doctype") or prefix.startswith("<html"):
        return "html"
    return "other"
