"""Orbit SOCKS5 proxy adapter tests. No live network."""

import asyncio
from unittest.mock import Mock

import pytest
import requests

from parsers.orbit import rest as orbit_rest
from parsers.orbit.client import open_orbit_websocket
from parsers.orbit.proxy import (
    OrbitProxyConfigError,
    configured_proxy_url,
    log_acquisition_mode,
    redact_proxy_url,
    requests_proxies,
    reraise_proxy_connect_failure,
)


AUTH_PROXY = "socks5://proxy-user:s3cret-pass@203.0.113.10:1080"


@pytest.fixture(autouse=True)
def _reset_proxy_log(monkeypatch):
    monkeypatch.setattr("parsers.orbit.proxy._logged_mode", False)


def test_absent_proxy_is_direct(monkeypatch):
    monkeypatch.delenv("ORBIT_SOCKS5_PROXY", raising=False)
    assert configured_proxy_url() is None
    assert requests_proxies() is None


def test_configured_proxy_is_passed_to_http(monkeypatch):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", AUTH_PROXY)
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        response = Mock()
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None
        response.status_code = 200
        return response

    monkeypatch.setattr(orbit_rest.requests, "post", fake_post)
    assert orbit_rest._download_page(0, [1]) == {"ok": True}
    assert captured["proxies"] == {"http": AUTH_PROXY, "https": AUTH_PROXY}
    assert captured["timeout"] == 20
    assert captured["headers"] is orbit_rest.HEADERS


def test_prematch_http_receives_proxy(monkeypatch):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", AUTH_PROXY)
    from parsers.orbit_prematch import rest as prematch_rest

    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"marketCatalogueList": {"content": [], "last": True}}
        response.text = "{}"
        return response

    monkeypatch.setattr(prematch_rest.requests, "post", fake_post)
    prematch_rest._post_page("TODAY", 0)
    assert captured["proxies"] == {"http": AUTH_PROXY, "https": AUTH_PROXY}


def test_direct_http_does_not_pass_proxies(monkeypatch):
    monkeypatch.delenv("ORBIT_SOCKS5_PROXY", raising=False)
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        response = Mock()
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None
        response.status_code = 200
        return response

    monkeypatch.setattr(orbit_rest.requests, "post", fake_post)
    orbit_rest._download_page(0, [1])
    assert "proxies" not in captured


def test_configured_proxy_opens_socks_socket_for_websocket(monkeypatch):
    import sys
    import types

    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", AUTH_PROXY)
    captured = {}
    socks_calls = {}
    fake_sock = object()

    class FakeProxy:
        @classmethod
        def from_url(cls, url):
            socks_calls["url"] = url
            return cls()

        async def connect(self, host, port):
            socks_calls["dest"] = (host, port)
            return fake_sock

    monkeypatch.setitem(
        sys.modules,
        "python_socks.async_.asyncio",
        types.SimpleNamespace(Proxy=FakeProxy),
    )

    async def fake_connect(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("parsers.orbit.client.websockets.connect", fake_connect)
    asyncio.run(
        open_orbit_websocket(
            "wss://www.orbitxch.com/customer/ws/multiple-market-prices/001/abcd1234/websocket",
            ping_interval=20,
            ping_timeout=20,
        )
    )
    assert captured["proxy"] is None
    assert captured["sock"] is fake_sock
    assert socks_calls["url"] == AUTH_PROXY
    assert socks_calls["dest"] == ("www.orbitxch.com", 443)
    assert captured["server_hostname"] == "www.orbitxch.com"


def test_quoted_proxy_env_is_accepted(monkeypatch):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", f'"{AUTH_PROXY}"')
    assert configured_proxy_url() == AUTH_PROXY


def test_direct_websocket_does_not_pass_proxy(monkeypatch):
    monkeypatch.delenv("ORBIT_SOCKS5_PROXY", raising=False)
    captured = {}

    async def fake_connect(url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("parsers.orbit.client.websockets.connect", fake_connect)
    asyncio.run(
        open_orbit_websocket(
            "wss://www.orbitxch.com/customer/ws/multiple-market-prices/001/abcd1234/websocket",
            ping_interval=None,
            ping_timeout=None,
        )
    )
    assert "proxy" not in captured
    assert captured["ping_interval"] is None


def test_authenticated_url_keeps_userinfo_for_libraries(monkeypatch):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", AUTH_PROXY)
    url = configured_proxy_url()
    assert url == AUTH_PROXY
    assert "proxy-user" in url
    assert "s3cret-pass" in url
    proxies = requests_proxies()
    assert proxies["https"] == AUTH_PROXY


def test_malformed_proxy_url_raises(monkeypatch):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", "http://203.0.113.10:1080")
    with pytest.raises(OrbitProxyConfigError, match="socks5"):
        configured_proxy_url()
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", "socks5://203.0.113.10")
    with pytest.raises(OrbitProxyConfigError, match="port"):
        configured_proxy_url()
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", "socks5://")
    with pytest.raises(OrbitProxyConfigError, match="host"):
        configured_proxy_url()


def test_proxy_credentials_never_appear_in_logs(monkeypatch, capsys):
    monkeypatch.setenv("ORBIT_SOCKS5_PROXY", AUTH_PROXY)
    log_acquisition_mode()
    out = capsys.readouterr().out
    assert "Orbit acquisition using SOCKS5 proxy" in out
    assert "proxy-user" not in out
    assert "s3cret-pass" not in out
    assert AUTH_PROXY not in out
    redacted = redact_proxy_url(AUTH_PROXY)
    assert "s3cret-pass" not in redacted
    assert "proxy-user" not in redacted
    assert "203.0.113.10:1080" in redacted


def test_proxy_connect_failure_message_has_no_credentials(monkeypatch, capsys):
    class FakeProxyError(Exception):
        pass

    monkeypatch.setattr(
        "parsers.orbit.proxy.reraise_proxy_connect_failure",
        reraise_proxy_connect_failure,
    )
    try:
        from websockets.exceptions import ProxyError as WsProxyError
    except ImportError:
        WsProxyError = FakeProxyError
    with pytest.raises(ConnectionError, match="Orbit SOCKS5 proxy connection failed") as exc:
        reraise_proxy_connect_failure(
            WsProxyError("socks5://proxy-user:s3cret-pass@203.0.113.10:1080")
        )
    assert "s3cret-pass" not in str(exc.value)
    assert "proxy-user" not in str(exc.value)
    out = capsys.readouterr().out
    assert "Orbit SOCKS5 proxy connection failed" in out
    assert "s3cret-pass" not in out
    assert "proxy-user" not in out


def test_existing_rest_403_still_classified(monkeypatch):
    monkeypatch.delenv("ORBIT_SOCKS5_PROXY", raising=False)
    response = Mock()
    response.status_code = 403
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    monkeypatch.setattr(orbit_rest.requests, "post", lambda *a, **k: response)
    from parsers.orbit.access import OrbitAccessError

    with pytest.raises(OrbitAccessError) as exc:
        orbit_rest._download_page(0, [1])
    assert exc.value.http_status == 403
    assert exc.value.category == "auth_or_access_denied"
