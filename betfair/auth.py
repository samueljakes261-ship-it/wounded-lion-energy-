"""
Verigood authenticated-session manager.

Preferred auth is a captured browser session from GET /valuebets:

    Authorization: Bearer <jwt>
    Cookie: sm_token=<jwt>

That state is loaded from BETFAIR_VALUEBETS_TOKEN / COOKIE or
verigood_session.json. Login (POST /api/auth/login) is only a fallback
when no captured session is present — it is not used to refresh a
captured session, because that flow has been unreliable.

There is no refresh-token schema. Captured JWTs live until they expire
or the endpoint returns 401. Values are never logged.
"""
from __future__ import annotations

import base64
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import requests

from betfair.config import (
    AUTH_RETRY_INITIAL_SECONDS,
    AUTH_RETRY_MAX_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    LOGIN_URL,
    SESSION_FILE,
    USER_AGENT,
)
from betfair.http import auth_headers

REFRESH_SKEW_SECONDS = 60
SM_TOKEN_COOKIE = "sm_token"
COOKIE_DOMAIN = "verigood.top"


class AuthError(Exception):
    """Login or token refresh failed. Message must never contain secrets."""


def _env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def strip_bearer(value: str) -> str:
    text = (value or "").strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return text


def token_from_cookie_header(header: str) -> Optional[str]:
    for part in (header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == SM_TOKEN_COOKIE and value.strip():
            return strip_bearer(value.strip())
    raw = strip_bearer(header)
    if raw.count(".") == 2:
        return raw
    return None


def jwt_exp_unix(token: str) -> Optional[int]:
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    try:
        return int(exp)
    except (TypeError, ValueError):
        return None


def session_file_path() -> Path:
    override = _env("BETFAIR_VALUEBETS_SESSION_FILE")
    if override:
        return Path(override)
    return SESSION_FILE


def load_session_file(path: Optional[Path] = None) -> dict:
    file_path = path or session_file_path()
    if not file_path.is_file():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def token_from_session_file(path: Optional[Path] = None) -> Optional[str]:
    data = load_session_file(path)
    for key in ("authorization", "access_token", "token", "Authorization"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return strip_bearer(raw)
    cookie = data.get("cookie") or data.get("Cookie")
    if isinstance(cookie, str):
        return token_from_cookie_header(cookie)
    return None


def configured_email() -> Optional[str]:
    return (
        _env("VERIGOOD_USERNAME")
        or _env("BETFAIR_VALUEBETS_EMAIL")
        or _env("BETFAIR_VALUEBETS_USERNAME")
    )


def configured_password() -> Optional[str]:
    return _env("VERIGOOD_PASSWORD") or _env("BETFAIR_VALUEBETS_PASSWORD")


def configured_cookie() -> Optional[str]:
    return _env("BETFAIR_VALUEBETS_COOKIE") or _env("VERIGOOD_COOKIE")


def configured_static_token() -> Optional[str]:
    for name in (
        "BETFAIR_VALUEBETS_TOKEN",
        "VALUEBETS_TOKEN",
        "VERIGOOD_ACCESS_TOKEN",
    ):
        raw = _env(name)
        if raw:
            return strip_bearer(raw)
    cookie = configured_cookie()
    if cookie:
        from_cookie = token_from_cookie_header(cookie)
        if from_cookie:
            return from_cookie
    return token_from_session_file()


def has_captured_session() -> bool:
    return bool(configured_static_token())


def credential_presence() -> dict[str, str]:
    """Safe diagnostics: PRESENT/MISSING only. Never the values."""
    presence = {
        "VERIGOOD_USERNAME": "PRESENT" if configured_email() else "MISSING",
        "VERIGOOD_PASSWORD": "PRESENT" if configured_password() else "MISSING",
        "BETFAIR_VALUEBETS_TOKEN": "PRESENT" if configured_static_token() else "MISSING",
        "BETFAIR_VALUEBETS_COOKIE": "PRESENT" if configured_cookie() else "MISSING",
        "VERIGOOD_SESSION_FILE": "PRESENT" if session_file_path().is_file() else "MISSING",
    }
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
        self._captured = False
        self._captured_rejected = False
        self._backoff_seconds = max(1.0, float(backoff_initial))
        self._backoff_initial = max(1.0, float(backoff_initial))
        self._backoff_max = max(self._backoff_initial, float(backoff_max))
        self._next_login_at: float = 0.0
        self._last_auth_at: Optional[float] = None
        self._last_auth_error: Optional[str] = None
        self._auth_success_count = 0
        self._auth_failure_count = 0
        self._seed_captured_session()

    def uses_captured_session(self) -> bool:
        return self._captured or has_captured_session()

    def headers(self) -> dict[str, str]:
        """Return Authorization headers. May POST /api/auth/login."""
        token = self._ensure_token()
        headers = dict(auth_headers(token))
        if token and (self._captured or has_captured_session()):
            headers["Cookie"] = f"{SM_TOKEN_COOKIE}={token}"
        return headers

    def invalidate(self, *, drop_cookies: bool = False) -> None:
        """Drop the cached access token. Optionally clear the cookie jar."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0
            if drop_cookies:
                self.session.cookies.clear()
            if self._captured:
                self._captured_rejected = True
            if self._last_auth_error is None and not self._captured:
                self._next_login_at = 0.0

    def mark_captured_rejected(self) -> None:
        with self._lock:
            self._captured_rejected = True
            self._access_token = None
            self._expires_at = 0.0

    def clear_session(self) -> None:
        """Drop token and cookies after a confirmed invalid session."""
        self.invalidate(drop_cookies=True)

    def health(self) -> dict:
        return {
            "last_authentication_at": self._last_auth_at,
            "last_auth_error": self._last_auth_error,
            "auth_success_count": self._auth_success_count,
            "auth_failure_count": self._auth_failure_count,
            "has_access_token": bool(
                self._access_token or (has_captured_session() and not self._captured_rejected)
            ),
            "captured_session": self.uses_captured_session(),
            "credential_presence": credential_presence(),
        }

    def _seed_captured_session(self) -> None:
        token = configured_static_token()
        if not token:
            return
        with self._lock:
            self._apply_captured_unlocked(token)

    def _apply_captured_unlocked(self, token: str) -> None:
        now = self._clock()
        exp = jwt_exp_unix(token)
        self._access_token = token
        self._captured = True
        self._captured_rejected = False
        self._expires_at = float(exp) if exp is not None else now + 7 * 24 * 3600
        self._last_auth_at = now
        self._last_auth_error = None
        self._auth_success_count += 1
        self.session.cookies.set(
            SM_TOKEN_COOKIE, token, domain=COOKIE_DOMAIN, path="/"
        )

    def _ensure_token(self) -> Optional[str]:
        with self._lock:
            now = self._clock()
            if self._captured or has_captured_session():
                if self._captured_rejected:
                    self._last_auth_error = "captured Verigood session rejected"
                    self._auth_failure_count += 1
                    raise AuthError(self._last_auth_error)
                if not self._access_token:
                    token = configured_static_token()
                    if not token:
                        self._last_auth_error = "captured Verigood session missing"
                        self._auth_failure_count += 1
                        raise AuthError(self._last_auth_error)
                    self._apply_captured_unlocked(token)
                    now = self._clock()
                if now >= (self._expires_at - REFRESH_SKEW_SECONDS):
                    self._last_auth_error = (
                        "captured Verigood session expired; paste a fresh "
                        "/valuebets Authorization header"
                    )
                    self._auth_failure_count += 1
                    raise AuthError(self._last_auth_error)
                return self._access_token

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
