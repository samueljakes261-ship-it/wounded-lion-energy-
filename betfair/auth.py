"""
Verigood authenticated-session manager.

Discovered from the public mOddshift OpenAPI spec (verigood.top/openapi.json):

    POST /api/auth/login
        Content-Type: application/json
        {email, password, remember_me}
        -> {access_token, token_type, expires_in}

    GET /valuebets
        security: HTTPBearer

There is no refresh-token schema and no cookie security scheme. Session
cookies, if the login response sets them, stay in the requests cookie
jar. Access tokens live in memory only and are dropped on process exit.

Credentials come from VERIGOOD_USERNAME / VERIGOOD_PASSWORD. This module
never logs those values, never writes them to disk, and never puts
cookies or tokens into source or .env as a session substitute.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Callable, Optional

import requests

from betfair.config import (
    AUTH_RETRY_INITIAL_SECONDS,
    AUTH_RETRY_MAX_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    LOGIN_URL,
    USER_AGENT,
)
from betfair.http import auth_headers

REFRESH_SKEW_SECONDS = 60


class AuthError(Exception):
    """Login or token refresh failed. Message must never contain secrets."""


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def configured_email() -> Optional[str]:
    return (
        _env("VERIGOOD_USERNAME")
        or _env("BETFAIR_VALUEBETS_EMAIL")
        or _env("BETFAIR_VALUEBETS_USERNAME")
    )


def configured_password() -> Optional[str]:
    return _env("VERIGOOD_PASSWORD") or _env("BETFAIR_VALUEBETS_PASSWORD")


def configured_static_token() -> Optional[str]:
    return _env("BETFAIR_VALUEBETS_TOKEN") or _env("VALUEBETS_TOKEN")


def credential_presence() -> dict[str, str]:
    """Safe diagnostics: PRESENT/MISSING only. Never the values."""
    presence = {
        "VERIGOOD_USERNAME": "PRESENT" if configured_email() else "MISSING",
        "VERIGOOD_PASSWORD": "PRESENT" if configured_password() else "MISSING",
    }
    if configured_static_token():
        presence["BETFAIR_VALUEBETS_TOKEN"] = "PRESENT"
    return presence


def credential_presence_log() -> str:
    parts = [f"{key}={value}" for key, value in credential_presence().items()]
    return " ".join(parts)


class VerigoodSessionManager:
    """
    Encapsulates Verigood HTTP authentication.

    The rest of Wounded Lion never sees cookies, bearer tokens, or
    passwords — only this object’s authenticated request headers and
    the shared requests.Session cookie jar.
    """

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        login_url: str = LOGIN_URL,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        post_fn: Optional[Callable[..., requests.Response]] = None,
        clock: Callable[[], float] = time.time,
        backoff_initial: float = AUTH_RETRY_INITIAL_SECONDS,
        backoff_max: float = AUTH_RETRY_MAX_SECONDS,
    ):
        self.session = session or requests.Session()
        self._login_url = login_url
        self._timeout = timeout
        self._post_fn = post_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._backoff_seconds = max(1.0, float(backoff_initial))
        self._backoff_initial = max(1.0, float(backoff_initial))
        self._backoff_max = max(self._backoff_initial, float(backoff_max))
        self._next_login_at: float = 0.0
        self._last_auth_at: Optional[float] = None
        self._last_auth_error: Optional[str] = None
        self._auth_success_count = 0
        self._auth_failure_count = 0

    def headers(self) -> dict[str, str]:
        """Return Authorization headers. May POST /api/auth/login."""
        return dict(auth_headers(self._ensure_token()))

    def invalidate(self, *, drop_cookies: bool = False) -> None:
        """Drop the cached access token. Optionally clear the cookie jar."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0
            if drop_cookies:
                self.session.cookies.clear()
            # A previously successful login is allowed to retry immediately
            # (401 on /valuebets). Failed logins keep their backoff.
            if self._last_auth_error is None:
                self._next_login_at = 0.0

    def clear_session(self) -> None:
        """Drop token and cookies after a confirmed invalid session."""
        self.invalidate(drop_cookies=True)

    def health(self) -> dict:
        return {
            "last_authentication_at": self._last_auth_at,
            "last_auth_error": self._last_auth_error,
            "auth_success_count": self._auth_success_count,
            "auth_failure_count": self._auth_failure_count,
            "has_access_token": bool(self._access_token or configured_static_token()),
            "credential_presence": credential_presence(),
        }

    def _ensure_token(self) -> Optional[str]:
        static = configured_static_token()
        if static:
            return static

        with self._lock:
            now = self._clock()
            if self._access_token and now < (self._expires_at - REFRESH_SKEW_SECONDS):
                return self._access_token
            if now < self._next_login_at:
                wait = int(math.ceil(self._next_login_at - now))
                raise AuthError(f"login backoff {wait}s")
            email = configured_email()
            password = configured_password()
            if not email or not password:
                self._last_auth_error = "VERIGOOD_USERNAME or VERIGOOD_PASSWORD not set"
                self._auth_failure_count += 1
                raise AuthError(self._last_auth_error)
            try:
                token, expires_in = self._login_unlocked(email, password)
            except AuthError as exc:
                self._last_auth_error = str(exc)
                self._auth_failure_count += 1
                self._next_login_at = now + self._backoff_seconds
                self._backoff_seconds = min(
                    self._backoff_max, self._backoff_seconds * 2
                )
                raise
            self._access_token = token
            self._expires_at = now + max(1, int(expires_in))
            self._last_auth_at = now
            self._last_auth_error = None
            self._auth_success_count += 1
            self._backoff_seconds = self._backoff_initial
            self._next_login_at = 0.0
            print(f"[BETFAIR] login succeeded expires_in={int(expires_in)}s")
            return token

    def _login_unlocked(self, email: str, password: str) -> tuple[str, int]:
        poster = self._post_fn or self.session.post
        try:
            response = poster(
                self._login_url,
                json={
                    "email": email,
                    "password": password,
                    "remember_me": True,
                },
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise AuthError(f"login request failed: {type(exc).__name__}") from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise AuthError(f"login failed HTTP {response.status_code}")

        content_type = ""
        headers = getattr(response, "headers", None)
        if headers is not None:
            content_type = str(headers.get("content-type") or "")
        if "html" in content_type.lower():
            raise AuthError("login returned HTML")

        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError("login returned non-JSON") from exc

        if not isinstance(body, dict):
            raise AuthError("login returned unexpected JSON")

        token = body.get("access_token")
        if not token or not isinstance(token, str):
            raise AuthError("login response missing access_token")

        expires_in = body.get("expires_in")
        try:
            expires_in_int = int(expires_in)
        except (TypeError, ValueError):
            expires_in_int = 3600

        return token, expires_in_int


# Backward-compatible name used by existing tests/callers.
ValuebetsAuth = VerigoodSessionManager
