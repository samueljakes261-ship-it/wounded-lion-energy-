"""Orbit REST/access classification -- no live network."""

from unittest.mock import Mock

import pytest
import requests

from parsers.orbit.access import (
    OrbitAccessError,
    classify_http_status,
    classify_response_body_kind,
)
from parsers.orbit import rest as orbit_rest


def test_403_is_access_denied_not_parser_failure():
    assert classify_http_status(403) == "auth_or_access_denied"
    assert classify_http_status(401) == "auth_or_access_denied"
    assert classify_http_status(200) == "ok"


def test_html_challenge_is_not_json_catalogue():
    assert classify_response_body_kind("text/html", "<!doctype html><html>") == "html"
    assert classify_response_body_kind("application/json", '{"marketCatalogueList":{}}') == "json"


def test_rest_http_403_raises_orbit_access_error(monkeypatch):
    response = Mock()
    response.status_code = 403
    response.raise_for_status.side_effect = requests.HTTPError(response=response)

    monkeypatch.setattr(
        orbit_rest.requests,
        "post",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(OrbitAccessError) as exc:
        orbit_rest._download_page(0, [1])

    assert exc.value.http_status == 403
    assert exc.value.category == "auth_or_access_denied"
    assert "Cookie" not in str(exc.value)
    assert "CSRF" not in str(exc.value)


def test_rest_network_error_is_classified(monkeypatch):
    monkeypatch.setattr(
        orbit_rest.requests,
        "post",
        Mock(side_effect=requests.Timeout("timed out")),
    )

    with pytest.raises(OrbitAccessError) as exc:
        orbit_rest._download_page(0, [1])

    assert exc.value.category == "network"
    assert exc.value.http_status is None
