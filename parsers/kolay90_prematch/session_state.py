"""Classify the attached Kolay90 page without printing secrets."""

from __future__ import annotations

from urllib.parse import urlsplit

from parsers.kolay90_prematch.agreement import is_agreement_page
from parsers.kolay90_prematch.login import _looks_like_challenge, inspect_page

AUTH_REQUIRED = "KOLAY90_AUTHENTICATION_REQUIRED"


def classify_session_state(
    url: str = "",
    title: str = "",
    text: str = "",
    has_password: bool = False,
    has_account: bool = False,
    has_login_control: bool = False,
    application: bool = False,
    cloudflare: bool = False,
) -> str:
    if cloudflare:
        return "CLOUDFLARE"
    if is_agreement_page(url, title, text):
        return "AGREEMENT"
    if has_password or (has_login_control and not has_account):
        return "LOGIN"
    if has_account or (application and not has_login_control):
        return "AUTHENTICATED_APP"
    host = (urlsplit(url or "").hostname or "").lower()
    if host == "kolay90.com" or host.endswith(".kolay90.com"):
        return "KOLAY90_UNKNOWN"
    return "UNKNOWN"


def classify_page(page) -> str:
    inspect = inspect_page(page)
    return classify_session_state(
        url=page.url or "",
        title=inspect.get("title") or "",
        text=inspect.get("text") or "",
        has_password=bool(inspect.get("has_password")),
        has_account=bool(inspect.get("has_account")),
        has_login_control=bool(inspect.get("has_login_control")),
        application=bool(inspect.get("application")),
        cloudflare=_looks_like_challenge(page) or bool(inspect.get("cloudflare")),
    )


def is_auth_required_state(state: str | None) -> bool:
    return state in {"CLOUDFLARE", "AGREEMENT", "LOGIN"}


def failure_for_state(state: str | None) -> str:
    return {
        "CLOUDFLARE": "cloudflare_challenge",
        "AGREEMENT": "agreement_page",
        "LOGIN": "login_page",
        "A": "cdp_attach_failed",
    }.get(state or "", "authentication_required")
