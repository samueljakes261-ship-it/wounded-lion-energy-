"""Unit tests for the isolated kolay90 prematch parser. No network, no cookies."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from parser import inspect_payload, parse_event, parse_payload, validate_against_raw, unwrap_events

FOOTBALL_EVENT = {
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
    "spor": "Futbol",
}

BASKETBALL_EVENT = {
    **FOOTBALL_EVENT,
    "_id": "evt-hoops",
    "ev_sahibi": "Team A",
    "deplasman": "Team B",
    "spor": "Basketbol",
    "oranlar": {"1": "1.80", "0": "3.00", "2": "4.10"},
}

AMBIGUOUS_EVENT = {
    "_id": "evt-unknown",
    "ev_sahibi": "Bocholt",
    "deplasman": "Rodinghausen",
    "zaman": {"sec": 1787400000},
    "oranlar": {"1": "2.38", "0": "3.45", "2": "2.50"},
    "type": 1,
}


def test_unwrap_hata_payload():
    assert unwrap_events({"hata": True, "mesaj": "Lütfen Tekrar Giriş Yapınız.."}) == []


def test_parse_known_1x2_keys_not_first_three_numbers():
    parsed = parse_event(FOOTBALL_EVENT)
    assert parsed is not None
    assert parsed.home_team == "Bocholt"
    assert parsed.away_team == "Rodinghausen"
    assert parsed.home_back == 2.38
    assert parsed.draw_back == 3.45
    assert parsed.away_back == 2.50
    assert parsed.feed_type == "prematch"
    assert parsed.sport == "football"
    assert parsed.bookmaker == "kolay90"


def test_accuracy_raw_vs_parsed():
    parsed = parse_event(FOOTBALL_EVENT)
    assert parsed is not None
    assert validate_against_raw(FOOTBALL_EVENT, parsed) == []


def test_rejects_missing_draw_key():
    item = dict(FOOTBALL_EVENT)
    item["oranlar"] = {"1": "2.38", "2": "2.50"}
    assert parse_event(item) is None


def test_rejects_basketball():
    assert parse_event(BASKETBALL_EVENT) is None


def test_rejects_ambiguous_sport():
    assert parse_event(AMBIGUOUS_EVENT) is None


def test_type_one_is_not_enough_to_call_it_football():
    inventory = inspect_payload([AMBIGUOUS_EVENT])
    assert "ambiguous" in inventory["football_discriminator"]
    assert parse_payload([AMBIGUOUS_EVENT]) == []


def test_payload_list_parse_count():
    parsed = parse_payload([FOOTBALL_EVENT, BASKETBALL_EVENT, AMBIGUOUS_EVENT])
    assert len(parsed) == 1
    assert parsed[0].event_id == "evt-bocholt"
