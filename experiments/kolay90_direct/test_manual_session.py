"""Offline tests for the manual Chrome Kolay90 experiment. No network."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from parsers.kolay90_prematch.parser import is_unauthenticated, parse_payload

from manual_session import (
    CDP_URL,
    classify_polls,
    classify_session_state,
    find_kolay90_page,
    parse_in_page_response,
    redact,
    summarize_fetch,
)


BOCHOLT = {
    "_id": "evt-bocholt",
    "ev_sahibi": "Bocholt",
    "deplasman": "Rodinghausen",
    "lig_id": 245759,
    "zaman": {"sec": 1893456000},
    "oranlar": {"1": "2.38", "0": "3.45", "2": "2.50"},
}


def test_cdp_url_is_localhost():
    assert CDP_URL == "http://127.0.0.1:9222"


def test_find_kolay90_page():
    rows = [
        {"url": "https://example.com/", "title": "Example"},
        {"url": "https://kolay90.com/sports", "title": "Kolay90"},
    ]
    found = find_kolay90_page(rows)
    assert found is not None
    assert found["title"] == "Kolay90"
    assert find_kolay90_page(rows[:1]) is None


def test_session_state_classification():
    assert classify_session_state(cloudflare=True) == "CLOUDFLARE"
    assert classify_session_state(
        url="https://kolay90.com/sozlesme.html", title="Sozlesme", text=""
    ) == "AGREEMENT"
    assert classify_session_state(has_password=True) == "LOGIN"
    assert classify_session_state(has_account=True) == "AUTHENTICATED_APP"
    assert classify_session_state(has_login_control=True) == "LOGIN"
    assert (
        classify_session_state(application=True, has_account=False, has_login_control=False)
        == "AUTHENTICATED_APP"
    )


def test_hata_true_is_unauthenticated():
    payload = {"hata": True, "mesaj": "Lutfen Tekrar Giris Yapiniz"}
    assert is_unauthenticated(payload) is True
    raw = {
        "status": 200,
        "content_type": "application/json",
        "payload": payload,
        "unauthenticated": True,
        "cloudflare": False,
    }
    summary = summarize_fetch(raw)
    assert summary["kind"] == "UNAUTHENTICATED_JSON"
    assert summary["authenticated"] is False


def test_valid_1x2_extraction():
    parsed = parse_payload([BOCHOLT])
    assert len(parsed) == 1
    assert parsed[0].home_odds == 2.38
    assert parsed[0].draw_odds == 3.45
    assert parsed[0].away_odds == 2.50
    raw = {
        "status": 200,
        "content_type": "application/json",
        "payload": [BOCHOLT],
        "unauthenticated": False,
        "cloudflare": False,
    }
    summary = summarize_fetch(raw)
    assert summary["kind"] == "AUTHENTICATED_JSON"
    assert summary["total_events"] == 1
    assert summary["valid_1x2"] == 1
    assert summary["examples"][0]["HOME"] == "2.38"


def test_repeated_polling_classifier():
    ok = {
        "kind": "AUTHENTICATED_JSON",
        "authenticated": True,
    }
    fail = {"kind": "UNAUTHENTICATED_JSON", "authenticated": False}
    assert classify_polls([ok, ok, ok, ok]) == "I"
    assert classify_polls([ok, ok, fail, ok]) == "H"
    assert classify_polls([fail]) == "F"
    assert classify_polls([{"kind": "403", "authenticated": False}]) == "G"


def test_parse_in_page_response_json_and_hata():
    ok = parse_in_page_response(
        {
            "status": 200,
            "contentType": "application/json",
            "text": '[{"_id":"1"}]',
        }
    )
    assert ok["status"] == 200
    assert ok["unauthenticated"] is False
    assert isinstance(ok["payload"], list)
    failed = parse_in_page_response(
        {
            "status": 200,
            "contentType": "application/json",
            "text": '{"hata": true, "mesaj": "Lutfen Tekrar Giris Yapiniz"}',
        }
    )
    assert failed["unauthenticated"] is True
    blocked = parse_in_page_response(
        {
            "status": 403,
            "contentType": "text/html",
            "text": "<html>Just a moment</html>",
        }
    )
    assert blocked["cloudflare"] is True


def test_redact_does_not_keep_apikey_or_cf_token():
    text = redact(
        "wss://browser.zenrows.com/?apikey=supersecret "
        "https://kolay90.com/?__cf_chl_rt_tk=tokensecret"
    )
    assert "supersecret" not in text
    assert "tokensecret" not in text
