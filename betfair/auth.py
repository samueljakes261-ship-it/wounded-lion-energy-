"""
Authenticated access to verigood.top/valuebets.

The public OpenAPI spec (mOddshift) documents:

    POST /api/auth/login
        {email, password, remember_me} -> {access_token, token_type, expires_in}

    GET /valuebets
        security: HTTPBearer

This module logs in with credentials from the environment and caches the
access token in memory until shortly before expiry. It never writes the
password or token to logs, diagnostics, or the opportunities cache.

A static BETFAIR_VALUEBETS_TOKEN skips login. An optional Cookie header
may be sent alongside Bearer if the operator pastes their own session
cookie, but Bearer is the documented API requirement.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

import requests

from betfair.config import (
    HTTP_TIMEOUT_SECONDS,
    LOGIN_URL,
    USER_AGENT,
)
from betfair.http import auth_headers, optional_cookie_header

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


def configured_cookie() -> Optional[str]:
    return _env("BETFAIR_VALUEBETS_COOKIE")


class ValuebetsAuth:
    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        login_url: str = LOGIN_URL,
        timeout: float = HTTP_TIMEOUT_SECONDS,
        post_fn: Optional[Callable[..., requests.Response]] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.session = session or requests.Session()
        self._login_url = login_url
        self._timeout = timeout
        self._post_fn = post_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def headers(self) -> dict[str, str]:
        """Return Authorization (and optional Cookie) headers. May POST login."""
        merged = dict(auth_headers(self._ensure_token()))
        merged.update(optional_cookie_header(configured_cookie()))
        return merged

    def invalidate(self) -> None:
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    def _ensure_token(self) -> Optional[str]:
        static = configured_static_token()
        if static:
            return static

        with self._lock:
            now = self._clock()
            if self._access_token and now < (self._expires_at - REFRESH_SKEW_SECONDS):
                return self._access_token
            email = configured_email()
            password = configured_password()
            if not email or not password:
                return self._access_token
            token, expires_in = self._login_unlocked(email, password)
            self._access_token = token
            self._expires_at = now + max(1, int(expires_in))
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
