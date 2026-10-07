import inspect
from urllib.parse import parse_qs, urlsplit

from kenyan.api_router import opportunities
from kenyan.models import KenyanMatchOdds
from kenyan.workers.base import Diagnostics
from kenyan.workers.poll_combine import combine_match_polls
from kenyan.config import (
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
)
from kenyan.http_utils import FetchResult
from kenyan.workers import bet22, betika, onexbet, sportpesa
from kenyan.workers.vzip_pages import fetch_vzip_all


def _ok(url, body, *, bytes_len=64):
    return FetchResult(
        url=url,
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=bytes_len,
        elapsed_seconds=0.01,
        json_body=body,
    )


def test_vzip_walks_after_cursor_until_short_page():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": 1}, {"I": 2}, {"I": 3}]})
        if after == "3":
            return _ok(url, {"Value": [{"I": 4}, {"I": 5}]})
        raise AssertionError(after)

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=3,
    )
    assert [event["I"] for event in envelope["Value"]] == [1, 2, 3, 4, 5]
    assert result.ok is True
    assert "after=3" in calls[1]
    assert len(calls) == 2


def test_vzip_keeps_paging_when_server_caps_below_requested_count():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": i} for i in range(1, 51)]})
        if after == "50":
            return _ok(url, {"Value": [{"I": i} for i in range(51, 101)]})
        if after == "100":
            return _ok(url, {"Value": [{"I": i} for i in range(101, 121)]})
        raise AssertionError(after)

    envelope, _ = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1&count=400",
        fetch=fake_fetch,
        page_count=400,
    )
    assert [event["I"] for event in envelope["Value"]] == list(range(1, 121))
    assert len(calls) == 3
    assert "after=50" in calls[1]
    assert "after=100" in calls[2]


def test_vzip_stops_when_server_ignores_after_and_repeats():
    def fake_fetch(url):
        return _ok(url, {"Value": [{"I": 10}, {"I": 11}, {"I": 12}]})

    envelope, _ = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=3,
        max_pages=5,
    )
    assert [event["I"] for event in envelope["Value"]] == [10, 11, 12]


def test_betika_requests_total_subtype_and_pages_until_meta_total(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        query = parse_qs(urlsplit(url).query)
        assert "18" in query.get("sub_type_id", [""])[0]
        page = int(query.get("page", ["1"])[0])
        assert query.get("limit", ["0"])[0] == str(betika.PAGE_LIMIT)
        if page == 1:
            rows = [{"match_id": index} for index in range(betika.PAGE_LIMIT)]
            return _ok(url, {"data": rows, "meta": {"total": betika.PAGE_LIMIT + 7}})
        rows = [{"match_id": betika.PAGE_LIMIT + index} for index in range(7)]
        return _ok(url, {"data": rows, "meta": {"total": betika.PAGE_LIMIT + 7}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, _ = betika._fetch_pages(betika.PREMATCH_URLS[0])
    assert len(payload["data"]) == betika.PAGE_LIMIT + 7
    assert any("page=2" in url for url in calls)


def test_betika_subtype_list_includes_total():
    assert "18" in betika.BETIKA_SUB_TYPES.split(",")


def test_onexbet_football_games1x2_is_not_capped_at_50():
    assert "count=250" in onexbet.PREMATCH_URL
    assert "count=50" not in onexbet.PREMATCH_URL
    assert any("Get1x2_VZip" in url for url in onexbet.PREMATCH_EXTRA_URLS)


def test_prematch_workers_poll_faster_than_live():
    assert KENYAN_PREMATCH_POLL_INTERVAL_SECONDS == 5
    assert KENYAN_LIVE_POLL_INTERVAL_SECONDS == 15
    pairs = (
        (sportpesa.build_live_worker(), sportpesa.build_prematch_worker()),
        (betika.build_live_worker(), betika.build_prematch_worker()),
        (onexbet.build_live_worker(), onexbet.build_prematch_worker()),
        (bet22.build_live_worker(), bet22.build_prematch_worker()),
    )
    for live, prematch in pairs:
        assert live._poll_interval_seconds == 15
        assert prematch._poll_interval_seconds == 5


def test_opportunities_default_mode_is_prematch():
    default = inspect.signature(opportunities).parameters["mode"].default
    assert default == "prematch"


def test_combine_polls_keeps_football_when_a_later_url_fails():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    match = KenyanMatchOdds(
        bookmaker="1xBet",
        competition="L",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=now,
        collected_at=now,
        event_id="1",
        status="PREMATCH",
    )
    combined, diagnostics = combine_match_polls(
        [
            ([match], Diagnostics(endpoint_status="ok", events_discovered=1, football_events=1)),
            ([], Diagnostics(endpoint_status="http_error", parser_error="HTTP 400")),
        ]
    )
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.parser_error is None
    assert combined == [match]
