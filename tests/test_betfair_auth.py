"""Betfair/Verigood authenticated session. HTTP is mocked; secrets never logged."""
import io
import logging

from betfair.auth import (
    AuthError,
    VerigoodSessionManager,
    credential_presence,
    credential_presence_log,
)
from betfair.http import FetchResult, classify_auth_failure
from betfair.worker import BetfairValuebetsWorker, acquire_once


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, cookies=None):
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self._payload = payload if payload is not None else {
            "access_token": "tok-abc",
            "token_type": "bearer",
            "expires_in": 3600,
        }
        self.cookies = cookies or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
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


def _ok_fetch(body=None, headers=None, session=None):
    return FetchResult(
        url="https://verigood.top/valuebets",
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=2,
        elapsed_seconds=0.01,
        json_body=body if body is not None else [],
    )


def _record(*, is_live, cluster="c1"):
    return {
        "cluster_id": cluster,
        "match_cluster_id": cluster,
        "home_team": "Home",
        "away_team": "Away",
        "start_time": "2026-10-01T18:45:00Z",
        "sport_key": "soccer",
        "league": "L",
        "market_label": "M",
        "direction": "LAY",
        "ref_bookmaker": "Betfair",
        "best_back_bookmaker": "Kolay91",
        "status": "VALUE",
        "outcome": "draw",
        "is_live": is_live,
        "detected_at": "2026-09-29T20:48:01Z",
        "first_seen_at": "2026-09-29T20:41:56Z",
        "last_updated_at": "2026-09-29T20:41:56Z",
        "guaranteed_profit": 1.5,
        "value_pct": 2.0,
        "back_stake": 100,
        "lay_stake": 50,
        "iddaa_odd": 2.1,
        "ref_odd": 2.0,
    }


def test_login_uses_verigood_env_and_sends_bearer(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    seen = {}

    def post_fn(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["headers"] = headers
        return FakeResponse()

    auth = VerigoodSessionManager(post_fn=post_fn)
    headers = auth.headers()
    assert headers["Authorization"] == "Bearer tok-abc"
    assert "token" not in headers
    assert "Cookie" not in headers
    assert seen["json"]["email"] == "myuser"
    assert seen["json"]["password"] == "secret-pass-xyz"
    assert seen["json"]["remember_me"] is True
    assert seen["url"].endswith("/api/auth/login")
    assert seen["headers"]["Content-Type"] == "application/json"


def test_login_set_cookie_stays_in_session_jar(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")

    def post_fn(url, json=None, headers=None, timeout=None):
        auth.session.cookies.set("sessionid", "from-login-set-cookie")
        return FakeResponse()

    auth = VerigoodSessionManager(post_fn=post_fn)
    auth.headers()
    assert auth.session.cookies.get("sessionid") == "from-login-set-cookie"


def test_valuebets_get_uses_authenticated_session(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    seen = {}

    def post_fn(url, json=None, headers=None, timeout=None):
        auth.session.cookies.set("sessionid", "from-login-set-cookie")
        return FakeResponse()

    def fetch_fn(url, headers=None, timeout=None, session=None):
        seen["authorization"] = (headers or {}).get("Authorization")
        seen["session_cookie"] = session.cookies.get("sessionid") if session else None
        seen["url"] = url
        return _ok_fetch([_record(is_live=False)])

    auth = VerigoodSessionManager(post_fn=post_fn)
    opportunities, diagnostics = acquire_once(fetch_fn=fetch_fn, auth=auth)
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.http_status_code == 200
    assert len(opportunities) == 1
    assert seen["authorization"] == "Bearer tok-abc"
    assert seen["session_cookie"] == "from-login-set-cookie"
    assert seen["url"].endswith("/valuebets")


def test_access_token_header_is_bearer_only(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
    headers = auth.headers()
    assert list(headers) == ["Authorization"]
    assert headers["Authorization"].startswith("Bearer ")


def test_no_refresh_token_schema_relogin_before_expiry(monkeypatch):
    """OpenAPI Token has no refresh_token — expiry uses another login."""
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    clock = {"now": 1_000.0}
    posts = {"n": 0}

    def post_fn(*args, **kwargs):
        posts["n"] += 1
        return FakeResponse(payload={
            "access_token": f"tok-{posts['n']}",
            "token_type": "bearer",
            "expires_in": 120,
        })

    auth = VerigoodSessionManager(post_fn=post_fn, clock=lambda: clock["now"])
    assert auth.headers()["Authorization"] == "Bearer tok-1"
    clock["now"] = 1_000.0 + 70  # past 60s skew of a 120s token
    assert auth.headers()["Authorization"] == "Bearer tok-2"
    assert posts["n"] == 2


def test_cached_token_does_not_login_again(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    calls = {"n": 0}

    def post_fn(*args, **kwargs):
        calls["n"] += 1
        return FakeResponse()

    auth = VerigoodSessionManager(post_fn=post_fn, clock=lambda: 1_000.0)
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

    auth = VerigoodSessionManager(post_fn=post_fn)
    assert auth.headers()["Authorization"] == "Bearer static-token"


def test_missing_credentials_are_an_auth_error_not_a_silent_401(monkeypatch):
    _clear_auth_env(monkeypatch)
    auth = VerigoodSessionManager(post_fn=lambda *args, **kwargs: FakeResponse())
    try:
        auth.headers()
        raise AssertionError("expected AuthError")
    except AuthError as exc:
        assert "VERIGOOD_USERNAME" in str(exc)


def test_failed_authentication(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")

    def post_fn(*args, **kwargs):
        return FakeResponse(status_code=401, payload={"detail": "bad"})

    auth = VerigoodSessionManager(post_fn=post_fn)
    try:
        auth.headers()
        raise AssertionError("expected AuthError")
    except AuthError as exc:
        assert "HTTP 401" in str(exc)
        assert "secret-pass-xyz" not in str(exc)


def test_login_backoff_avoids_hammering(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    clock = {"now": 1_000.0}
    posts = {"n": 0}

    def post_fn(*args, **kwargs):
        posts["n"] += 1
        return FakeResponse(status_code=401, payload={"detail": "bad"})

    auth = VerigoodSessionManager(
        post_fn=post_fn,
        clock=lambda: clock["now"],
        backoff_initial=5,
        backoff_max=60,
    )
    try:
        auth.headers()
    except AuthError:
        pass
    try:
        auth.headers()
    except AuthError as exc:
        assert "backoff" in str(exc)
    assert posts["n"] == 1


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
                is_auth_failure=True,
            )
        assert headers["Authorization"] == "Bearer tok-2"
        return _ok_fetch([])

    auth = VerigoodSessionManager(post_fn=post_fn)
    opportunities, diagnostics = acquire_once(fetch_fn=fetch_fn, auth=auth)
    assert diagnostics.endpoint_status == "ok"
    assert opportunities == []
    assert fetches["n"] == 2
    assert posts["n"] == 2


def test_successful_recovery_after_auth_failure(monkeypatch):
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
            return FetchResult(
                url=url,
                ok=False,
                status_code=401,
                content_type="application/json",
                response_size_bytes=26,
                elapsed_seconds=0.01,
                error="HTTP 401",
                is_auth_failure=True,
            )
        return _ok_fetch([_record(is_live=True)])

    auth = VerigoodSessionManager(post_fn=post_fn)
    worker = BetfairValuebetsWorker(auth=auth, fetch_fn=fetch_fn)
    worker._run_one_cycle()
    status = worker.get_status()
    assert status["health"] == "RUNNING"
    assert status["live_records"] == 1
    assert worker.get_opportunities()[0].is_live is True


def test_generic_403_is_not_treated_as_auth_failure():
    assert classify_auth_failure(status_code=403, body_preview="rate limited") is False
    assert classify_auth_failure(status_code=403, body_preview="Token gerekli") is True
    assert classify_auth_failure(status_code=401, body_preview="") is True
    assert classify_auth_failure(
        status_code=302, location="https://verigood.top/login"
    ) is True
    assert classify_auth_failure(
        status_code=302, location="https://verigood.top/elsewhere"
    ) is False


def test_empty_response_is_ok_not_fake_data(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
    _, diagnostics = acquire_once(
        fetch_fn=lambda *a, **k: _ok_fetch([]),
        auth=auth,
    )
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.raw_count == 0


def test_invalid_json_is_not_healthy(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
    _, diagnostics = acquire_once(
        fetch_fn=lambda *a, **k: FetchResult(
            url="https://verigood.top/valuebets",
            ok=False,
            status_code=200,
            content_type="application/json",
            response_size_bytes=12,
            elapsed_seconds=0.01,
            error="invalid JSON: boom",
        ),
        auth=auth,
    )
    assert diagnostics.endpoint_status == "invalid_json"


def test_html_login_page_is_not_healthy(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
    _, diagnostics = acquire_once(
        fetch_fn=lambda *a, **k: FetchResult(
            url="https://verigood.top/valuebets",
            ok=False,
            status_code=200,
            content_type="text/html",
            response_size_bytes=80,
            elapsed_seconds=0.01,
            error="HTML response (not JSON)",
        ),
        auth=auth,
    )
    assert diagnostics.endpoint_status == "html_response"


def test_live_and_prematch_classification(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
    opportunities, diagnostics = acquire_once(
        fetch_fn=lambda *a, **k: _ok_fetch(
            [_record(is_live=True, cluster="live"), _record(is_live=False, cluster="pre")]
        ),
        auth=auth,
    )
    assert diagnostics.live_count == 1
    assert diagnostics.prematch_count == 1
    classes = {item.live_classification for item in opportunities}
    assert classes == {"LIVE", "PREMATCH"}


def test_poll_interval_is_three_seconds():
    from betfair.config import POLL_INTERVAL_SECONDS

    assert POLL_INTERVAL_SECONDS == 3


def test_no_credential_leakage_in_logs_or_status(monkeypatch, capsys):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("VERIGOOD_USERNAME", "myuser")
    monkeypatch.setenv("VERIGOOD_PASSWORD", "secret-pass-xyz")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logging.getLogger().addHandler(handler)
    try:
        auth = VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse())
        auth.headers()
        worker = BetfairValuebetsWorker(
            auth=auth,
            fetch_fn=lambda *a, **k: _ok_fetch([]),
        )
        worker._run_one_cycle()
        status = worker.get_status()
    finally:
        logging.getLogger().removeHandler(handler)

    printed = capsys.readouterr().out + stream.getvalue() + str(status)
    assert "secret-pass-xyz" not in printed
    assert "tok-abc" not in printed
    assert "Bearer " not in printed
    presence = credential_presence()
    assert presence["VERIGOOD_USERNAME"] == "PRESENT"
    assert presence["VERIGOOD_PASSWORD"] == "PRESENT"
    assert "secret-pass-xyz" not in credential_presence_log()
    assert status["credential_presence"]["VERIGOOD_PASSWORD"] == "PRESENT"
    assert status["has_access_token"] is True


def test_missing_credentials_mark_worker_failed(monkeypatch):
    _clear_auth_env(monkeypatch)
    worker = BetfairValuebetsWorker(
        auth=VerigoodSessionManager(post_fn=lambda *a, **k: FakeResponse()),
        fetch_fn=lambda *a, **k: _ok_fetch([]),
    )
    worker._run_one_cycle()
    status = worker.get_status()
    assert status["health"] == "FAILED"
    assert "not set" in (status["error"] or "")
