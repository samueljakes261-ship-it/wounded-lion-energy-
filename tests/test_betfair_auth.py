"""Betfair/verigood login. HTTP is mocked; passwords must never appear in logs."""
from betfair.auth import AuthError, ValuebetsAuth
from betfair.http import FetchResult
from betfair.worker import acquire_once


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {
            "access_token": "tok-abc",
            "token_type": "bearer",
            "expires_in": 3600,
        }

    def json(self):
        return self._payload


def _clear_auth_env(monkeypatch):
    for name in (
        "VERIGOOD_USERNAME",
        "VERIGOOD_PASSWORD",
        "BETFAIR_VALUEBETS_EMAIL",
        "BETFAIR_VALUEBETS_USERNAME",
        "BETFAIR_VALUEBETS_PASSWORD",
        "BETFAIR_VALUEBETS_TOKEN",
        "VALUEBETS_TOKEN",
        "BETFAIR_VALUEBETS_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_login_uses_verigood_env_and_sends_bearer(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    seen = {}

    def post_fn(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return FakeResponse()

    auth = ValuebetsAuth(post_fn=post_fn)
    headers = auth.headers()
    assert headers["Authorization"] == "Bearer tok-abc"
    assert seen["json"]["email"] == "myuser"
    assert seen["json"]["password"] == "secret-pass-xyz"
    assert seen["json"]["remember_me"] is True
    assert "/api/auth/login" in seen["url"]


def test_cached_token_does_not_login_again(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    calls = {"n": 0}

    def post_fn(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    auth = ValuebetsAuth(post_fn=post_fn, clock=lambda: 1_000.0)
    auth.headers()
    auth.headers()
    assert calls["n"] == 1


def test_static_token_skips_login(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("BETFAIR_VALUEBETS_TOKEN", "static-token")
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")

    def post_fn(*args, **kwargs):
        raise AssertionError("login must not run when TOKEN is set")

    auth = ValuebetsAuth(post_fn=post_fn)
    assert auth.headers()["Authorization"] == "Bearer static-token"


def test_login_failure_message_omits_password(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")

    def post_fn(*args, **kwargs):
        return FakeResponse(status_code=401, payload={"detail": "bad"})

    auth = ValuebetsAuth(post_fn=post_fn)
    try:
        auth.headers()
        raise AssertionError("expected AuthError")
    except AuthError as exc:
        text = str(exc)
        assert "secret-pass-xyz" not in text
        assert "HTTP 401" in text


def test_401_poll_relogs_in_once(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    posts = {"n": 0}

    def post_fn(*args, **kwargs):
        posts["n"] += 1
        return FakeResponse(payload={
            "access_token": f"tok-{posts['n']}",
            "token_type": "bearer",
            "expires_in": 3600,
        })

    fetches = {"n": 0}

    def fetch_fn(url, headers=None, timeout=None, session=None):
        fetches["n"] += 1
        if fetches["n"] == 1:
            assert headers["Authorization"] == "Bearer tok-1"
            return FetchResult(
                url=url,
                ok=False,
                status_code=401,
                content_type="application/json",
                response_size_bytes=20,
                elapsed_seconds=0.01,
                error="HTTP 401",
            )
        assert headers["Authorization"] == "Bearer tok-2"
        return FetchResult(
            url=url,
            ok=True,
            status_code=200,
            content_type="application/json",
            response_size_bytes=2,
            elapsed_seconds=0.01,
            json_body=[],
        )

    auth = ValuebetsAuth(post_fn=post_fn)
    opportunities, diagnostics = acquire_once(fetch_fn=fetch_fn, auth=auth)
    assert diagnostics.endpoint_status == "ok"
    assert opportunities == []
    assert fetches["n"] == 2
    assert posts["n"] == 2
