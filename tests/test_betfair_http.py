"""Verigood HTTP fetch classification. No live network."""
from betfair.http import classify_auth_failure, fetch_json


class DummyResponse:
    def __init__(self, status_code, content=b"", content_type="application/json", location=None):
        self.status_code = status_code
        self.content = content
        self.headers = {}
        if content_type:
            self.headers["content-type"] = content_type
        if location:
            self.headers["location"] = location

    def json(self):
        import json

        return json.loads(self.content.decode("utf-8"))


class DummySession:
    def __init__(self, response, captured=None):
        self._response = response
        self.captured = captured if captured is not None else {}

    def get(self, url, headers=None, timeout=None, allow_redirects=None):
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["allow_redirects"] = allow_redirects
        return self._response


def test_fetch_json_success_uses_minimum_headers():
    captured = {}
    session = DummySession(
        DummyResponse(200, b"[]", "application/json"),
        captured,
    )
    result = fetch_json(
        "https://verigood.top/valuebets",
        headers={"Authorization": "Bearer tok"},
        session=session,
    )
    assert result.ok is True
    assert result.status_code == 200
    assert result.json_body == []
    assert captured["allow_redirects"] is False
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert "sec-ch-ua" not in captured["headers"]


def test_fetch_json_html_200_is_not_ok():
    session = DummySession(DummyResponse(200, b"<html>login</html>", "text/html"))
    result = fetch_json(session=session)
    assert result.ok is False
    assert "HTML" in (result.error or "")


def test_fetch_json_401_is_auth_failure():
    session = DummySession(
        DummyResponse(401, b'{"detail":"Token gerekli"}', "application/json")
    )
    result = fetch_json(session=session)
    assert result.ok is False
    assert result.status_code == 401
    assert result.is_auth_failure is True
    assert result.error == "HTTP 401"


def test_fetch_json_invalid_json():
    session = DummySession(DummyResponse(200, b"not-json", "application/json"))
    result = fetch_json(session=session)
    assert result.ok is False
    assert "invalid JSON" in (result.error or "")


def test_fetch_json_login_redirect_is_auth_failure():
    session = DummySession(
        DummyResponse(302, b"", "text/html", location="https://verigood.top/login")
    )
    result = fetch_json(session=session)
    assert result.ok is False
    assert result.is_auth_failure is True


def test_classify_403_requires_auth_wording():
    assert classify_auth_failure(status_code=403, body_preview="forbidden by waf") is False
    assert classify_auth_failure(status_code=403, body_preview="invalid token") is True
