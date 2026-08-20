"""
Tests for api.py's route handlers.

No real HTTP server/client is spun up (httpx/TestClient isn't a
project dependency) -- FastAPI route handlers here are plain functions
decorated with @app.get(), so they can be called directly like any
other function while monkeypatching the module-level data sources they
read from. This still proves exactly what the endpoint returns for a
given underlying state, which is what matters for these tests.
"""

import api


def test_opportunities_endpoint_returns_cache_verbatim(monkeypatch):
    fake_cache = [{"homeTeam": "A", "awayTeam": "B", "home": {"odds": 2.157}}]
    monkeypatch.setattr(api, "get_cached_opportunities", lambda: fake_cache)

    result = api.opportunities()

    assert result == fake_cache
    # Byte-for-byte: the odds value must not be re-rounded/reformatted
    # by the endpoint itself.
    assert result[0]["home"]["odds"] == 2.157


def test_opportunities_endpoint_returns_empty_list_when_no_cache(monkeypatch):
    monkeypatch.setattr(api, "get_cached_opportunities", lambda: [])

    assert api.opportunities() == []


def test_status_endpoint_returns_collector_status_verbatim(monkeypatch):
    fake_status = {
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "matchedEvents": 3,
        "opportunityCount": 0,
        "collectors": {
            "orbit": {"name": "Orbit", "collectorStatus": "RUNNING"},
        },
    }
    monkeypatch.setattr(api, "get_collector_status", lambda: fake_status)

    result = api.status()

    assert result == fake_status
    # The core Issue 2 guarantee, visible at the API boundary: RUNNING
    # with 0 opportunities is a valid, healthy combination.
    assert result["opportunityCount"] == 0
    assert result["collectors"]["orbit"]["collectorStatus"] == "RUNNING"


def test_health_endpoint_unaffected():
    assert api.health() == {"status": "healthy"}


def test_root_endpoint_unaffected():
    body = api.root()
    assert body["application"] == "ArbScanner"
    assert body["status"] == "running"
