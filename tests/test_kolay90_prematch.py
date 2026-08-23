"""Isolated Kolay90 prematch parser/feed tests. No network."""

from __future__ import annotations

from datetime import datetime, timezone

from parsers.kolay90_prematch.feed import Kolay90PrematchFeed
from parsers.kolay90_prematch.parser import (
    extract_1x2,
    is_unauthenticated,
    parse_event,
    parse_payload,
    start_time_from_event,
    unwrap_events,
    validate_against_raw,
)

BOCHOLT = {
    "_id": "evt-bocholt",
    "ev_sahibi": "Bocholt",
    "deplasman": "Rodinghausen",
    "lig_id": 245759,
    "code": 598,
    "mbs": 1,
    "zaman": {"sec": 1787400000},
    "oranlar": {"1": "2.38", "0": "3.45", "2": "2.50"},
    "type": 1,
    "zs": "Cmt 15:00",
}


def test_one_x_two_mapping_not_first_numeric_keys():
    parsed = parse_event(BOCHOLT)
    assert parsed is not None
    assert parsed.home_odds == 2.38
    assert parsed.draw_odds == 3.45
    assert parsed.away_odds == 2.50
    assert parsed.raw_home == "2.38"
    assert parsed.raw_draw == "3.45"
    assert parsed.raw_away == "2.50"
    assert parsed.match.feed_type == "prematch"
    assert parsed.match.bookmaker == "kolay90"
    assert parsed.event_id == "evt-bocholt"
    assert parsed.bookmaker_code == "598"
    assert parsed.match.tournament_id == "245759"
    assert validate_against_raw(BOCHOLT, parsed) == []


def test_missing_odds_only_draw_key_rejected():
    item = {**BOCHOLT, "oranlar": {"0": "8.75"}}
    assert extract_1x2(item) is None
    assert parse_event(item) is None


def test_malformed_event_ignored():
    assert parse_event("not-an-object") is None
    assert parse_payload(["x", None, 3]) == []


def test_missing_oranlar():
    item = {k: v for k, v in BOCHOLT.items() if k != "oranlar"}
    assert parse_event(item) is None


def test_missing_event_id():
    item = {**BOCHOLT, "_id": ""}
    assert parse_event(item) is None
    item.pop("_id")
    assert parse_event(item) is None


def test_invalid_decimal_odds():
    item = {**BOCHOLT, "oranlar": {"1": "abc", "0": "3.45", "2": "2.50"}}
    assert parse_event(item) is None


def test_unauthenticated_response():
    payload = {"hata": True, "mesaj": "Lütfen Tekrar Giriş Yapınız.. Yada Sisteme Bağlı Olduğunuzu Kontrol Ediniz."}
    assert is_unauthenticated(payload) is True
    assert unwrap_events(payload) == []
    assert parse_payload(payload) == []


def test_valid_authenticated_list():
    parsed = parse_payload([BOCHOLT])
    assert len(parsed) == 1
    assert parsed[0].home_team == "Bocholt"


def test_timestamp_conversion():
    start = start_time_from_event(BOCHOLT)
    assert start == datetime.fromtimestamp(1787400000, tz=timezone.utc)
    parsed = parse_event(BOCHOLT)
    assert parsed is not None
    assert parsed.match.start_time == start


def test_duplicate_events_last_wins():
    first = {**BOCHOLT, "oranlar": {"1": "2.00", "0": "3.00", "2": "4.00"}}
    second = {**BOCHOLT, "oranlar": {"1": "2.10", "0": "3.10", "2": "4.10"}}
    parsed = parse_payload([first, second])
    assert len(parsed) == 1
    assert parsed[0].home_odds == 2.10


def test_non_football_rejected_when_sport_present():
    item = {**BOCHOLT, "spor": "Basketbol", "_id": "hoops"}
    assert parse_event(item) is None


def test_feed_keeps_last_good_on_auth_expiry():
    feed = Kolay90PrematchFeed()
    good = feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 100,
            "json": True,
            "payload": [BOCHOLT],
            "looks_html": False,
            "unauthenticated": False,
            "error": None,
            "cloudflare": False,
        }
    )
    assert good["ok"] is True
    assert len(feed.last_good()) == 1
    expired = feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 80,
            "json": True,
            "payload": {"hata": True, "mesaj": "Lütfen Tekrar Giriş Yapınız.."},
            "looks_html": False,
            "unauthenticated": True,
            "error": None,
            "cloudflare": False,
        }
    )
    assert expired["ok"] is False
    assert expired["kept_last_good"] is True
    assert expired["failure"] == "login_expired"
    assert len(expired["matches"]) == 1
    assert expired["matches"][0].home_team == "Bocholt"


def test_feed_keeps_last_good_on_cloudflare_html():
    feed = Kolay90PrematchFeed()
    feed._apply_fetch(
        {
            "status": 200,
            "content_type": "application/json",
            "bytes": 100,
            "json": True,
            "payload": [BOCHOLT],
            "looks_html": False,
            "unauthenticated": False,
            "error": None,
            "cloudflare": False,
        }
    )
    blocked = feed._apply_fetch(
        {
            "status": 403,
            "content_type": "text/html",
            "bytes": 5000,
            "json": False,
            "payload": None,
            "looks_html": True,
            "unauthenticated": False,
            "error": None,
            "cloudflare": True,
        }
    )
    assert blocked["kept_last_good"] is True
    assert blocked["failure"] == "cloudflare_html"
    assert len(feed.last_good()) == 1
