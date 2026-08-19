"""
Backend half of the Vercel-connectivity diagnosis/fix (see
frontend/src/lib/api-config.ts and frontend/.env.example for the
frontend half).

Covers, using a real ASGI request/response cycle (fastapi.testclient,
which drives Starlette's actual CORSMiddleware -- calling the route
functions directly, as tests/test_api_endpoints.py does, would never
exercise CORS at all):

- CORS explicitly allows the real production Vercel origin.
- CORS does NOT fall back to a wildcard and does NOT allow arbitrary
  origins.
- Local dev origins keep working.
- /opportunities and /status responses match the exact field names the
  frontend's TypeScript `Opportunity`/`Leg`/`CollectorHealth` types
  expect (see frontend/src/routes/index.tsx).
- Neither endpoint's response can ever contain a backend secret.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api
import collector
from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector
from engine.match_finder import MatchFinder
from engine.stake_calculator import StakeCalculator
from models.match import MatchOdds


PRODUCTION_VERCEL_ORIGIN = "https://woundedlionenergy.vercel.app"
LEGACY_VERCEL_ORIGIN = "https://wounded-lion-energy.vercel.app"
LOCAL_DEV_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:5173",
    "http://localhost:3000",
]


@pytest.fixture
def client():
    return TestClient(api.app)


# ----------------------------------------------------------------------
# CORS
# ----------------------------------------------------------------------


def test_cors_allows_the_real_production_vercel_origin(client):
    response = client.get(
        "/opportunities", headers={"Origin": PRODUCTION_VERCEL_ORIGIN}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PRODUCTION_VERCEL_ORIGIN


def test_cors_allows_the_legacy_hyphenated_vercel_origin(client):
    response = client.get(
        "/opportunities", headers={"Origin": LEGACY_VERCEL_ORIGIN}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LEGACY_VERCEL_ORIGIN


@pytest.mark.parametrize("origin", LOCAL_DEV_ORIGINS)
def test_cors_allows_local_dev_origins(client, origin):
    response = client.get("/opportunities", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_does_not_use_a_wildcard_allow_origin(client):
    response = client.get(
        "/opportunities", headers={"Origin": PRODUCTION_VERCEL_ORIGIN}
    )

    assert response.headers["access-control-allow-origin"] != "*"


def test_cors_rejects_an_arbitrary_unrelated_origin(client):
    response = client.get(
        "/opportunities", headers={"Origin": "https://some-random-site.example.com"}
    )

    # The request still succeeds server-side (CORS is enforced by the
    # BROWSER refusing to expose the response, not the server refusing
    # to respond) -- what must be true is that this origin is never
    # echoed back as an allowed origin.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_for_production_origin_is_allowed(client):
    response = client.options(
        "/opportunities",
        headers={
            "Origin": PRODUCTION_VERCEL_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PRODUCTION_VERCEL_ORIGIN


# ----------------------------------------------------------------------
# Response schema matches the frontend's TypeScript expectations
# (frontend/src/routes/index.tsx: Opportunity / Leg / CollectorHealth)
# ----------------------------------------------------------------------


def _build_one_real_opportunity_cache_entry():
    now = datetime.now(timezone.utc)

    home = MatchOdds(
        bookmaker="OnWin", competition="Test League", sport="football",
        market="1X2", home_team="Home FC", away_team="Away FC",
        home_odds=2.5, draw_odds=3.4, away_odds=3.2,
        start_time=now, collected_at=now,
    )
    away = MatchOdds(
        bookmaker="Betkanyon", competition="Test League", sport="football",
        market="Match Odds", home_team="Home FC", away_team="Away FC",
        home_odds=2.4, draw_odds=3.5, away_odds=4.5,
        start_time=now, collected_at=now,
    )

    finder = MatchFinder()
    events = list(finder.find([home, away]))
    assert events, "fixture matches must find each other as the same event"
    event = events[0]

    selector = BestOddsSelector()
    best = selector.select(event)

    result = ArbitrageDetector().detect(best)
    assert result.arbitrage_exists, "fixture must actually be an arbitrage for this test to be meaningful"

    plan = StakeCalculator().calculate(result=result, bankroll=100.0)

    class _Opportunity:
        pass

    opportunity = _Opportunity()
    opportunity.event = event
    opportunity.result = result
    opportunity.stake_plan = plan

    return opportunity


REQUIRED_OPPORTUNITY_FIELDS = {
    "competition", "sport", "market", "homeTeam", "awayTeam",
    "profitPercentage", "impliedProbability", "roi", "guaranteedProfit",
    "guaranteedReturn", "totalStake", "generatedAt", "home", "draw", "away",
}
REQUIRED_LEG_FIELDS = {"bookmaker", "odds", "stake", "side", "market", "collectedAt"}


def test_opportunities_endpoint_schema_matches_frontend_expectations(client, monkeypatch, tmp_path):
    opportunity = _build_one_real_opportunity_cache_entry()

    cache_file = tmp_path / "cached_opportunities.json"
    monkeypatch.setattr(collector, "CACHE_FILE", cache_file)
    collector._write_cache([opportunity])

    response = client.get("/opportunities")
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, list)
    assert len(body) == 1

    entry = body[0]
    missing = REQUIRED_OPPORTUNITY_FIELDS - entry.keys()
    assert not missing, f"API response is missing fields the frontend requires: {missing}"

    for leg_name in ("home", "draw", "away"):
        leg = entry[leg_name]
        missing_leg_fields = REQUIRED_LEG_FIELDS - leg.keys()
        assert not missing_leg_fields, (
            f"'{leg_name}' leg is missing fields the frontend requires: {missing_leg_fields}"
        )

    assert isinstance(entry["profitPercentage"], (int, float))
    assert isinstance(entry["home"]["odds"], (int, float))


def test_status_endpoint_schema_matches_frontend_collector_health_type(client, monkeypatch, tmp_path):
    fake_status = {
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "matchedEvents": 2,
        "opportunityCount": 1,
        "collectors": {
            "orbit": {
                "name": "Orbit",
                "collectorStatus": "RUNNING",
                "lastSuccessfulCollection": "2026-01-01T00:00:00+00:00",
                "lastCollectionAttempt": "2026-01-01T00:00:00+00:00",
                "ageSeconds": 1.2,
                "eventsCollected": 5,
                "error": None,
            },
        },
    }
    monkeypatch.setattr(api, "get_collector_status", lambda: fake_status)

    response = client.get("/status")
    assert response.status_code == 200

    body = response.json()
    required_top_level = {"generatedAt", "matchedEvents", "opportunityCount", "collectors"}
    assert required_top_level.issubset(body.keys())

    required_collector_fields = {
        "name", "collectorStatus", "lastSuccessfulCollection",
        "lastCollectionAttempt", "ageSeconds", "eventsCollected", "error",
    }
    orbit = body["collectors"]["orbit"]
    assert required_collector_fields.issubset(orbit.keys())


# ----------------------------------------------------------------------
# No secrets ever leave the backend through these public endpoints
# ----------------------------------------------------------------------

FORBIDDEN_SUBSTRINGS = (
    "MASTER_CREDENTIAL_KEY", "ZENROWS_BROWSER_WS", "apikey=",
    "credentials.json", "BRIGHTDATA_PASSWORD", "SCRAPFLY_API_KEY",
)


def test_opportunities_response_never_contains_secrets(client, monkeypatch, tmp_path):
    opportunity = _build_one_real_opportunity_cache_entry()
    cache_file = tmp_path / "cached_opportunities.json"
    monkeypatch.setattr(collector, "CACHE_FILE", cache_file)
    collector._write_cache([opportunity])

    response = client.get("/opportunities")
    body_text = response.text

    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in body_text


def test_status_response_never_contains_secrets(client, monkeypatch):
    monkeypatch.setattr(
        api,
        "get_collector_status",
        lambda: {
            "generatedAt": None, "matchedEvents": 0, "opportunityCount": 0,
            "collectors": {},
        },
    )

    response = client.get("/status")
    body_text = response.text

    for forbidden in FORBIDDEN_SUBSTRINGS:
        assert forbidden not in body_text
