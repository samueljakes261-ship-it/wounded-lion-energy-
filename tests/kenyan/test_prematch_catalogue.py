"""PREMATCH walks the real catalogue end, not a hidden page ceiling."""
from urllib.parse import parse_qs, urlsplit

from kenyan.config import (
    KENYAN_BETIKA_MAX_PAGES,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_SPORTPESA_LIVE_MAX_PAGES,
    KENYAN_VZIP_MAX_PAGES,
)
from kenyan.http_utils import FetchResult, fetch_json
from kenyan.workers import betika, onexbet, sportpesa
from kenyan.workers.base import Diagnostics, derive_catalogue_status
from kenyan.workers.vzip_pages import (
    CHAMP_EVENT_CAP,
    build_champ_events_url,
    build_champs_zip_url,
    fetch_vzip_all,
    fetch_vzip_by_champs,
)


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


def test_live_caps_remain_for_fast_live_walks():
    assert KENYAN_VZIP_MAX_PAGES == 80
    assert KENYAN_BETIKA_MAX_PAGES == 80
    assert KENYAN_SPORTPESA_LIVE_MAX_PAGES == 40
    assert KENYAN_PREMATCH_RUNAWAY_PAGES > 80


def test_prematch_vzip_continues_past_live_page_cap():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        start = 1 if after is None else int(after) + 1
        if start > 90 * 50:
            return _ok(url, {"Value": [{"I": start}]})
        return _ok(url, {"Value": [{"I": index} for index in range(start, start + 50)]})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=KENYAN_PREMATCH_RUNAWAY_PAGES,
    )
    assert len(envelope["Value"]) == 90 * 50 + 1
    assert result.snapshot_complete is True
    assert result.page_cap_hit is False
    assert result.pages_fetched == 91
    assert len(calls) == 91


def test_prematch_vzip_runaway_is_incomplete_not_complete():
    def fake_fetch(url):
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        start = 1 if after is None else int(after) + 1
        return _ok(url, {"Value": [{"I": index} for index in range(start, start + 50)]})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=5,
    )
    assert len(envelope["Value"]) == 5 * 50
    assert result.page_cap_hit is True
    assert result.snapshot_complete is False
    assert derive_catalogue_status(
        Diagnostics(
            endpoint_status="ok",
            events_discovered=len(envelope["Value"]),
            page_cap_hit=True,
            snapshot_complete=False,
        )
    ) == "partial"


def test_common_1x2_keeps_three_wrapper_home_draw_away_alignment():
    source = open("kenyan/parsers/_common_1x2.py", encoding="utf-8").read()
    assert "wrappers[:3]" in source
    assert "HOME/DRAW/AWAY" in source


def test_onexbet_prematch_vzip_uses_runaway_not_live_cap():
    source = open(onexbet.__file__, encoding="utf-8").read()
    assert "KENYAN_PREMATCH_RUNAWAY_PAGES" in source
    assert "KENYAN_VZIP_MAX_PAGES if status == LIVE else KENYAN_PREMATCH_RUNAWAY_PAGES" in source
    assert "fetch_vzip_by_champs" in source
    assert "if status == LIVE:" in source


def test_champs_zip_query_puts_sport_and_champs_first():
    zip_url = build_champs_zip_url(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true"
    )
    assert "GetChampsZip?" in zip_url
    assert zip_url.split("?", 1)[1].startswith("sport=1&")
    event_url = build_champ_events_url(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
        99,
    )
    assert event_url.split("?", 1)[1].startswith("champs=99&count=50&")
    assert "sports=" not in event_url


def test_prematch_vzip_champs_walk_collects_more_than_the_50_event_window():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return _ok(
                url,
                {
                    "Success": True,
                    "Value": [
                        {"LI": 10, "GC": 2, "SI": 1},
                        {"LI": 11, "GC": 3, "SI": 1},
                        {"LI": 12, "GC": 2, "SI": 1},
                    ],
                },
            )
        champ = parse_qs(urlsplit(url).query).get("champs", [None])[0]
        start = int(champ) * 10
        count = 2 if champ != "11" else 3
        return _ok(url, {"Value": [{"I": start + index} for index in range(count)]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        champ_concurrency=1,
    )
    assert [event["I"] for event in envelope["Value"]] == [100, 101, 110, 111, 112, 120, 121]
    assert result.snapshot_complete is True
    assert result.page_cap_hit is False
    assert result.source_total == 7
    assert result.unique_event_ids == 7
    assert result.terminal_reason == "source_total"
    assert result.pages_fetched == 4
    assert "sports=" not in result.url or "Get1x2_VZip" in result.url


def test_champ_event_url_does_not_send_rejected_continuation_params():
    url = build_champ_events_url(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
        1146817,
    )
    query = parse_qs(urlsplit(url).query)
    assert "after" not in query
    assert "skip" not in query
    assert "offset" not in query
    assert "page" not in query
    assert "ts" not in query
    assert query.get("champs") == ["1146817"]
    assert query.get("count") == [str(CHAMP_EVENT_CAP)]
    assert "sports" not in query


def test_prematch_vzip_champ_at_50_cap_with_higher_gc_is_partial():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return _ok(url, {"Success": True, "Value": [{"LI": 99, "GC": 90, "SI": 1}]})
        return _ok(url, {"Value": [{"I": index} for index in range(1, CHAMP_EVENT_CAP + 1)]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        champ_concurrency=1,
    )
    assert len(envelope["Value"]) == CHAMP_EVENT_CAP
    assert result.snapshot_complete is False
    assert result.terminal_reason == "page_size_cap"
    assert result.source_total == 90
    assert result.capped_partitions == 1


def test_prematch_vzip_gc_shortfall_below_cap_is_partial():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return _ok(url, {"Success": True, "Value": [{"LI": 7, "GC": 20, "SI": 1}]})
        return _ok(url, {"Value": [{"I": index} for index in range(1, 11)]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        champ_concurrency=1,
    )
    assert len(envelope["Value"]) == 10
    assert result.snapshot_complete is False
    assert result.terminal_reason == "source_total_shortfall"
    assert result.source_total == 20
    assert result.capped_partitions == 0


def test_prematch_vzip_duplicate_ids_across_champs_are_counted():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return _ok(
                url,
                {
                    "Success": True,
                    "Value": [
                        {"LI": 1, "GC": 2, "SI": 1},
                        {"LI": 2, "GC": 2, "SI": 1},
                    ],
                },
            )
        return _ok(url, {"Value": [{"I": 10}, {"I": 11}]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        champ_concurrency=1,
    )
    assert [event["I"] for event in envelope["Value"]] == [10, 11]
    assert result.unique_event_ids == 2
    assert result.duplicate_events == 2
    assert result.source_total == 4
    assert result.snapshot_complete is False
    assert result.terminal_reason == "source_total_shortfall"


def test_catalogue_status_source_total_shortfall_is_partial():
    assert (
        derive_catalogue_status(
            Diagnostics(
                endpoint_status="ok",
                events_discovered=10,
                unique_event_ids=10,
                source_total=20,
                snapshot_complete=False,
                terminal_reason="source_total_shortfall",
            )
        )
        == "partial"
    )


def test_combine_polls_keeps_page_size_cap_when_mixed_with_complete():
    from kenyan.workers.poll_combine import combine_match_polls

    _, diagnostics = combine_match_polls(
        [
            (
                [],
                Diagnostics(
                    endpoint_status="ok",
                    events_discovered=50,
                    unique_event_ids=50,
                    source_total=90,
                    snapshot_complete=False,
                    terminal_reason="page_size_cap",
                    capped_partitions=1,
                ),
            ),
            (
                [],
                Diagnostics(
                    endpoint_status="ok",
                    events_discovered=10,
                    unique_event_ids=10,
                    source_total=10,
                    snapshot_complete=True,
                    terminal_reason="source_total",
                ),
            ),
        ]
    )
    assert diagnostics.snapshot_complete is False
    assert diagnostics.terminal_reason == "page_size_cap"
    assert diagnostics.capped_partitions == 1
    assert diagnostics.catalogue_status == "partial"


def test_prematch_vzip_champs_http_error_falls_back_incomplete():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return FetchResult(
                url=url,
                ok=False,
                status_code=406,
                content_type="application/problem+json",
                response_size_bytes=10,
                elapsed_seconds=0.01,
                error="HTTP 406",
            )
        return _ok(url, {"Value": [{"I": index} for index in range(1, 51)]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        champ_concurrency=1,
    )
    assert len(envelope["Value"]) == 50
    assert result.snapshot_complete is False
    assert result.terminal_reason == "champs_http_error"


def test_prematch_vzip_champs_walks_past_80_championships():
    def fake_fetch(url):
        if "GetChampsZip" in url:
            return _ok(
                url,
                {
                    "Success": True,
                    "Value": [{"LI": 1000 + index, "GC": 1, "SI": 1} for index in range(90)],
                },
            )
        champ = int(parse_qs(urlsplit(url).query).get("champs", ["0"])[0])
        return _ok(url, {"Value": [{"I": champ}]})

    envelope, result = fetch_vzip_by_champs(
        "https://example.test/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en",
        fetch=fake_fetch,
        max_champs=KENYAN_PREMATCH_RUNAWAY_PAGES,
        champ_concurrency=1,
    )
    assert len(envelope["Value"]) == 90
    assert result.snapshot_complete is True
    assert result.pages_fetched == 91
    assert result.pages_fetched > KENYAN_VZIP_MAX_PAGES


def test_betika_prematch_pages_until_meta_total_past_live_cap(monkeypatch):
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        total = 82 * betika.PAGE_LIMIT + 4
        if page < 83:
            rows = [
                {"match_id": (page - 1) * betika.PAGE_LIMIT + index}
                for index in range(betika.PAGE_LIMIT)
            ]
            return _ok(url, {"data": rows, "meta": {"total": total}})
        rows = [
            {"match_id": 82 * betika.PAGE_LIMIT + index} for index in range(4)
        ]
        return _ok(url, {"data": rows, "meta": {"total": total}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=KENYAN_PREMATCH_RUNAWAY_PAGES,
    )
    assert len(payload["data"]) == 82 * betika.PAGE_LIMIT + 4
    assert result.snapshot_complete is True
    assert result.page_cap_hit is False
    assert result.source_total == 82 * betika.PAGE_LIMIT + 4
    assert len(calls) == 83
    assert len(calls) > KENYAN_BETIKA_MAX_PAGES


def test_betika_live_still_stops_at_live_cap(monkeypatch):
    calls = []

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        rows = [{"match_id": page * 1000 + index} for index in range(betika.PAGE_LIMIT)]
        return _ok(url, {"data": rows, "meta": {"total": 1_000_000}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.LIVE_URL,
        max_pages=KENYAN_BETIKA_MAX_PAGES,
    )
    assert result.page_cap_hit is True
    assert result.snapshot_complete is False
    assert len(calls) == KENYAN_BETIKA_MAX_PAGES
    assert len(payload["data"]) == KENYAN_BETIKA_MAX_PAGES * betika.PAGE_LIMIT


def test_sportpesa_prematch_pages_until_short_page_past_former_40(monkeypatch):
    calls = []

    def fake_fetch(url, headers=None, timeout=None, retries=0):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("pag_min", ["1"])[0])
        if page < 45:
            body = [
                {
                    "id": page * 100 + index,
                    "sport": {"id": 1},
                    "competitors": [{"name": "A"}, {"name": "B"}],
                    "dateTimestamp": 1_700_000_000_000,
                    "markets": [],
                }
                for index in range(sportpesa.PREMATCH_PAGE_COUNT)
            ]
            return _ok(url, body)
        return _ok(url, [{"id": 4500, "sport": {"id": 1}}])

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.pages_fetched == 45
    assert diagnostics.page_cap_hit is False
    assert diagnostics.snapshot_complete is True
    assert diagnostics.catalogue_status == "complete"
    assert len(calls) == 45
    assert len(calls) > KENYAN_SPORTPESA_LIVE_MAX_PAGES
    assert isinstance(matches, list)


def test_catalogue_status_values():
    assert (
        derive_catalogue_status(
            Diagnostics(endpoint_status="ok", events_discovered=0, snapshot_complete=True)
        )
        == "empty_complete"
    )
    assert (
        derive_catalogue_status(
            Diagnostics(
                endpoint_status="ok",
                events_discovered=10,
                snapshot_complete=True,
            )
        )
        == "complete"
    )
    assert (
        derive_catalogue_status(
            Diagnostics(endpoint_status="http_error", parser_error="HTTP 500")
        )
        == "failed"
    )
    assert (
        derive_catalogue_status(
            Diagnostics(
                endpoint_status="ok",
                events_discovered=10,
                snapshot_complete=False,
            )
        )
        == "partial"
    )


def test_prematch_vzip_runaway_sets_terminal_reason():
    def fake_fetch(url):
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        start = 1 if after is None else int(after) + 1
        return _ok(url, {"Value": [{"I": index} for index in range(start, start + 50)]})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=5,
    )
    assert result.terminal_reason == "runaway_guard"
    assert result.first_cursor == "1"
    assert result.last_cursor == "250"
    assert len(envelope["Value"]) == 250


def test_prematch_vzip_http_error_after_first_page_is_partial():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": index} for index in range(1, 51)]})
        return FetchResult(
            url=url,
            ok=False,
            status_code=500,
            content_type="text/plain",
            response_size_bytes=3,
            elapsed_seconds=0.01,
            error="HTTP 500",
        )

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=10,
    )
    assert len(envelope["Value"]) == 50
    assert result.snapshot_complete is False
    assert result.terminal_reason == "http_error"
    assert result.page_cap_hit is False


def test_prematch_vzip_empty_page_after_full_walk_is_complete():
    def fake_fetch(url):
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": index} for index in range(1, 51)]})
        if after == "50":
            return _ok(url, {"Value": [{"I": index} for index in range(51, 101)]})
        return _ok(url, {"Value": []})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=10,
    )
    assert [event["I"] for event in envelope["Value"]] == list(range(1, 101))
    assert result.snapshot_complete is True
    assert result.terminal_reason == "empty_page"
    assert result.page_cap_hit is False


def test_prematch_vzip_short_page_is_not_requested_count():
    def fake_fetch(url):
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": index} for index in range(1, 16)]})
        if after == "15":
            return _ok(url, {"Value": [{"I": index} for index in range(16, 31)]})
        return _ok(url, {"Value": [{"I": 31}, {"I": 32}]})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=400,
        max_pages=10,
    )
    assert [event["I"] for event in envelope["Value"]] == list(range(1, 33))
    assert result.snapshot_complete is True
    assert result.terminal_reason == "short_page"


def test_betika_prematch_continues_when_first_page_shorter_than_requested(monkeypatch):
    calls = []

    def fake_fetch(url, retries=0):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        total = 150
        if page <= 3:
            rows = [{"match_id": (page - 1) * 50 + index} for index in range(50)]
            return _ok(url, {"data": rows, "meta": {"total": total}})
        return _ok(url, {"data": [], "meta": {"total": total}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=KENYAN_PREMATCH_RUNAWAY_PAGES,
        honor_requested_short_page=False,
    )
    assert 50 < betika.PAGE_LIMIT
    assert len(payload["data"]) == 150
    assert result.snapshot_complete is True
    assert result.terminal_reason == "source_total"
    assert result.source_total == 150
    assert len(calls) == 3


def test_betika_prematch_observed_size_without_meta_total(monkeypatch):
    calls = []

    def fake_fetch(url, retries=0):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        if page < 4:
            rows = [{"match_id": (page - 1) * 40 + index} for index in range(40)]
            return _ok(url, {"data": rows, "meta": {}})
        rows = [{"match_id": 120 + index} for index in range(7)]
        return _ok(url, {"data": rows, "meta": {}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=KENYAN_PREMATCH_RUNAWAY_PAGES,
        honor_requested_short_page=False,
    )
    assert len(payload["data"]) == 127
    assert result.snapshot_complete is True
    assert result.terminal_reason == "short_page"
    assert len(calls) == 4


def test_betika_live_still_stops_on_short_requested_page(monkeypatch):
    calls = []

    def fake_fetch(url, retries=0):
        calls.append(url)
        rows = [{"match_id": index} for index in range(50)]
        return _ok(url, {"data": rows, "meta": {"total": 10000}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.LIVE_URL,
        max_pages=KENYAN_BETIKA_MAX_PAGES,
        honor_requested_short_page=True,
    )
    assert len(payload["data"]) == 50
    assert len(calls) == 1
    assert result.snapshot_complete is True
    assert result.terminal_reason == "short_page"


def test_betika_prematch_runaway_is_incomplete(monkeypatch):
    def fake_fetch(url, retries=0):
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        rows = [{"match_id": page * 1000 + index} for index in range(betika.PAGE_LIMIT)]
        return _ok(url, {"data": rows, "meta": {"total": 1_000_000}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=5,
        honor_requested_short_page=False,
    )
    assert result.page_cap_hit is True
    assert result.snapshot_complete is False
    assert result.terminal_reason == "runaway_guard"
    assert len(payload["data"]) == 5 * betika.PAGE_LIMIT


def test_betika_empty_before_source_total_is_incomplete(monkeypatch):
    def fake_fetch(url, **_kwargs):
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        if page == 1:
            rows = [{"match_id": index} for index in range(50)]
            return _ok(url, {"data": rows, "meta": {"total": 500}})
        return _ok(url, {"data": [], "meta": {"total": 500}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=KENYAN_PREMATCH_RUNAWAY_PAGES,
        honor_requested_short_page=False,
    )
    assert len(payload["data"]) == 50
    assert result.snapshot_complete is False
    assert result.terminal_reason == "empty_before_source_total"


def test_betika_zero_new_ids_is_incomplete(monkeypatch):
    def fake_fetch(url, retries=0):
        rows = [{"match_id": index + 1} for index in range(betika.PAGE_LIMIT)]
        return _ok(url, {"data": rows, "meta": {"total": 10000}})

    monkeypatch.setattr(betika, "fetch_json", fake_fetch)
    payload, result = betika._fetch_pages(
        betika.PREMATCH_URLS[0],
        max_pages=5,
        honor_requested_short_page=False,
    )
    assert len(payload["data"]) == betika.PAGE_LIMIT
    assert result.snapshot_complete is False
    assert result.terminal_reason == "zero_new_ids"


def test_sportpesa_prematch_continues_when_first_page_shorter_than_requested(monkeypatch):
    calls = []

    def fake_fetch(url, headers=None, timeout=None, retries=0):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query).get("pag_min", ["1"])[0])
        count = int(parse_qs(urlsplit(url).query).get("pag_count", ["15"])[0])
        assert count == sportpesa.PREMATCH_PAGE_COUNT
        observed = 10
        if page < 5:
            body = [
                {
                    "id": (page - 1) * observed + index,
                    "sport": {"id": 1},
                    "competitors": [{"name": "A"}, {"name": "B"}],
                    "dateTimestamp": 1_700_000_000_000,
                    "markets": [],
                }
                for index in range(observed)
            ]
            return _ok(url, body)
        return _ok(
            url,
            [{"id": 40, "sport": {"id": 1}, "competitors": [{"name": "A"}, {"name": "B"}]}],
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert "pag_count=15" in calls[0]
    assert diagnostics.pages_fetched == 5
    assert diagnostics.snapshot_complete is True
    assert diagnostics.catalogue_status == "complete"
    assert diagnostics.terminal_reason == "short_page"
    assert diagnostics.unique_event_ids == 41
    assert diagnostics.page_cap_hit is False
    assert isinstance(matches, list)


def test_sportpesa_prematch_http_error_mid_walk_is_partial(monkeypatch):
    def fake_fetch(url, headers=None, timeout=None, retries=0):
        page = int(parse_qs(urlsplit(url).query).get("pag_min", ["1"])[0])
        if page == 1:
            body = [
                {
                    "id": index,
                    "sport": {"id": 1},
                    "competitors": [{"name": "A"}, {"name": "B"}],
                    "dateTimestamp": 1_700_000_000_000,
                    "markets": [],
                }
                for index in range(sportpesa.PREMATCH_PAGE_COUNT)
            ]
            return _ok(url, body)
        return FetchResult(
            url=url,
            ok=False,
            status_code=503,
            content_type="text/plain",
            response_size_bytes=3,
            elapsed_seconds=0.01,
            error="HTTP 503",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.snapshot_complete is False
    assert diagnostics.catalogue_status == "partial"
    assert diagnostics.terminal_reason == "http_error"
    assert diagnostics.unique_event_ids == sportpesa.PREMATCH_PAGE_COUNT
    assert isinstance(matches, list)


def test_sportpesa_prematch_runaway_is_incomplete(monkeypatch):
    def fake_fetch(url, headers=None, timeout=None, retries=0):
        page = int(parse_qs(urlsplit(url).query).get("pag_min", ["1"])[0])
        body = [
            {
                "id": page * 100 + index,
                "sport": {"id": 1},
                "competitors": [{"name": "A"}, {"name": "B"}],
                "dateTimestamp": 1_700_000_000_000,
                "markets": [],
            }
            for index in range(sportpesa.PREMATCH_PAGE_COUNT)
        ]
        return _ok(url, body)

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    monkeypatch.setattr(sportpesa, "PREMATCH_MAX_PAGES_PER_CYCLE", 4)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.page_cap_hit is True
    assert diagnostics.snapshot_complete is False
    assert diagnostics.catalogue_status == "partial"
    assert diagnostics.terminal_reason == "runaway_guard"
    assert diagnostics.pages_fetched == 4
    assert isinstance(matches, list)


def test_fetch_json_retries_5xx_and_not_4xx(monkeypatch):
    monkeypatch.setattr("kenyan.http_utils.time.sleep", lambda *_args, **_kwargs: None)

    class ErrorResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {"content-type": "text/plain"}
            self.content = b"err"
            self.text = "err"

    class OkResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b'{"ok": true}'
        text = '{"ok": true}'

        def json(self):
            return {"ok": True}

    class Session500:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            if self.calls < 3:
                return ErrorResponse(500)
            return OkResponse()

    session = Session500()
    result = fetch_json("https://example.test/retry", session=session, retries=2)
    assert result.ok is True
    assert session.calls == 3

    class Session400:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            return ErrorResponse(400)

    session400 = Session400()
    result400 = fetch_json("https://example.test/retry", session=session400, retries=2)
    assert result400.ok is False
    assert session400.calls == 1

    class Session406:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            if self.calls < 3:
                return ErrorResponse(406)
            return OkResponse()

    session406 = Session406()
    result406 = fetch_json("https://example.test/retry", session=session406, retries=2)
    assert result406.ok is True
    assert session406.calls == 3
