"""PREMATCH walks the real catalogue end, not a hidden page ceiling."""
from urllib.parse import parse_qs, urlsplit

from kenyan.config import (
    KENYAN_BETIKA_MAX_PAGES,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_SPORTPESA_LIVE_MAX_PAGES,
    KENYAN_VZIP_MAX_PAGES,
)
from kenyan.http_utils import FetchResult
from kenyan.workers import betika, onexbet, sportpesa
from kenyan.workers.base import Diagnostics, derive_catalogue_status
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


def test_onexbet_prematch_vzip_uses_runaway_not_live_cap():
    source = open(onexbet.__file__, encoding="utf-8").read()
    assert "KENYAN_PREMATCH_RUNAWAY_PAGES" in source
    assert "KENYAN_VZIP_MAX_PAGES if status == LIVE else KENYAN_PREMATCH_RUNAWAY_PAGES" in source


def test_betika_prematch_pages_until_meta_total_past_live_cap(monkeypatch):
    calls = []

    def fake_fetch(url):
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

    def fake_fetch(url):
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

    def fake_fetch(url, headers=None, timeout=None):
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
