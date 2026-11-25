"""Kolay91 live odds reuse the prematch 1X2 parser. No network."""

from datetime import datetime, timezone

from parsers.kolay90_prematch.live import (
    POLL_INTERVAL_SECONDS,
    PollSlot,
    adapt_upcoming_payload,
    claim_due,
    diagnose,
    merge_matches,
    parse_endpoint_payload,
    schedule_after,
)
from parsers.kolay90_prematch.live_worker import Kolay90LiveWorker
from parsers.kolay90_prematch.parser import parse_event, parse_payload

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
LIVE = {
    "_id": "evt-live",
    "ev_sahibi": "Bocholt",
    "deplasman": "Rodinghausen",
    "lig_id": 245759,
    "code": 598,
    "zaman": {"sec": 1_000_000_000},
    "oranlar": {"1": "2.38", "0": "3.45", "2": "2.50"},
    "zs": "Canli 12'",
}
PREMATCH = {
    **LIVE,
    "_id": "evt-pre",
    "zaman": {"sec": 1_893_456_000},
    "zs": "Cmt 15:00",
}


def _raw(payload, status=200, **extra):
    body = {
        "status": status,
        "json": True,
        "payload": payload,
        "looks_html": False,
        "unauthenticated": False,
        "cloudflare": False,
        "error": None,
        "retry_after": None,
    }
    body.update(extra)
    return body


def test_polling_interval_is_five_seconds():
    assert POLL_INTERVAL_SECONDS == 5.0


def test_getmaclar_live_row_uses_prematch_1x2_and_stays_out_of_prematch():
    parsed = parse_endpoint_payload("getMaclar", {"maclar": [LIVE, PREMATCH]}, now=NOW)
    assert len(parsed) == 1
    assert parsed[0].event_id == "evt-live"
    assert parsed[0].home_odds == 2.38
    assert parsed[0].draw_odds == 3.45
    assert parsed[0].away_odds == 2.50
    assert parsed[0].match.feed_type == "live"
    assert parsed[0].match.bookmaker == "kolay90"
    assert parsed[0].match.market == "1X2"
    assert parse_event(LIVE, now=NOW) is None
    assert [row.event_id for row in parse_payload({"maclar": [LIVE, PREMATCH]}, )] == [] or (
        parse_payload({"maclar": [PREMATCH]})[0].match.feed_type == "prematch"
    )
    prematch = parse_payload({"maclar": [LIVE, PREMATCH]})
    assert [row.event_id for row in prematch] == ["evt-pre"]
    assert prematch[0].match.feed_type == "prematch"


def test_upcoming_endpoint_maps_into_the_same_1x2_record():
    payload = {
        "data": [
            {
                "id": "up-1",
                "homeTeam": "Alpha",
                "awayTeam": "Beta",
                "startTime": "2026-11-25T18:00:00+00:00",
                "sport": "football",
                "odds": {"home": "1.90", "draw": "3.40", "away": "4.20"},
            }
        ]
    }
    adapted = adapt_upcoming_payload(payload)
    assert adapted["maclar"][0]["ev_sahibi"] == "Alpha"
    assert adapted["maclar"][0]["oranlar"] == {"1": "1.90", "0": "3.40", "2": "4.20"}
    parsed = parse_endpoint_payload("live_upcoming", payload, now=NOW)
    assert len(parsed) == 1
    assert parsed[0].match.feed_type == "live"
    assert parsed[0].home_odds == 1.90
    assert parse_payload(payload) == []


def test_malformed_and_empty_are_not_successful_updates():
    assert diagnose(_raw({"maclar": []}), 0, 0) == "no_live_events"
    assert diagnose(_raw({"maclar": [{"_id": "x"}]}), 1, 0) == "parse_failure"
    assert diagnose(
        {
            "status": None,
            "json": False,
            "payload": None,
            "looks_html": False,
            "unauthenticated": False,
            "cloudflare": False,
            "error": "TimeoutError",
        },
        0,
        0,
    ) == "network"
    assert diagnose(_raw({}, status=429), 0, 0) == "rate_limited"
    assert diagnose(_raw({"hata": True}, unauthenticated=True), 0, 0) == "invalid"


def test_one_endpoint_failure_keeps_the_other_endpoints_odds():
    books = {}

    def fetcher(name, url):
        del url
        if name == "getMaclar":
            return _raw({"maclar": [LIVE]})
        return _raw({}, error="TimeoutError", json=False, payload=None)

    worker = Kolay90LiveWorker(poll_interval=5, fetcher=fetcher)
    worker._poll_endpoint("getMaclar", worker._slots["getMaclar"])
    first = worker.get_matches()
    assert len(first) == 1
    assert first[0].feed_type == "live"
    stamped = worker.get_status()["last_update_at"]
    worker._poll_endpoint("live_upcoming", worker._slots["live_upcoming"])
    status = worker.get_status()
    assert len(status["matches"]) == 1
    assert status["matches"][0].home_team == "Bocholt"
    assert status["endpoints"]["getMaclar"]["diagnosis"] == "ok"
    assert status["endpoints"]["live_upcoming"]["diagnosis"] == "network"
    assert status["last_update_at"] == stamped
    assert status["endpoints"]["live_upcoming"]["last_success_at"] is None
    books["kept"] = True


def test_empty_response_does_not_refresh_the_success_timestamp():
    def fetcher(name, url):
        del name, url
        return _raw({"maclar": []})

    worker = Kolay90LiveWorker(poll_interval=5, fetcher=fetcher)
    worker._poll_endpoint("getMaclar", worker._slots["getMaclar"])
    status = worker.get_status()
    assert status["last_update_at"] is None
    assert status["endpoints"]["getMaclar"]["diagnosis"] == "no_live_events"
    assert status["consecutive_failures"] == 0


def test_slots_do_not_overlap_and_back_off_on_429():
    slots = {"getMaclar": PollSlot(5), "live_upcoming": PollSlot(5)}
    slots["getMaclar"].in_flight = True
    assert claim_due(slots, 0) == "live_upcoming"
    slots["live_upcoming"].in_flight = True
    assert claim_due(slots, 0) is None
    schedule_after(slots["getMaclar"], now=10, interval=5, diagnosis="rate_limited", retry_after=12)
    assert slots["getMaclar"].next_monotonic == 22
    schedule_after(slots["live_upcoming"], now=10, interval=5, diagnosis="ok", retry_after=None)
    assert slots["live_upcoming"].next_monotonic == 15


def test_newer_live_price_replaces_the_same_fixture_without_dropping_feed_type():
    older = parse_endpoint_payload("getMaclar", {"maclar": [LIVE]}, collected_at=NOW, now=NOW)[0].match
    newer_item = {**LIVE, "oranlar": {"1": "2.10", "0": "3.30", "2": "3.10"}}
    later = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
    newer = parse_endpoint_payload(
        "getMaclar", {"maclar": [newer_item]}, collected_at=later, now=NOW
    )[0].match
    merged = merge_matches([older, newer])
    assert len(merged) == 1
    assert merged[0].home_odds == 2.10
    assert merged[0].feed_type == "live"
