"""
Persistent 1xBet workers (one for LIVE, one for PREMATCH).
"""
import time

from kenyan.config import (
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_LIVE_STALE_AFTER_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    KENYAN_VZIP_MAX_PAGES,
    LIVE,
    ONEXBET,
)
from kenyan.http_utils import copy_cache_headers, fetch_json
from kenyan.parsers._common_1x2 import (
    extract_1x2_from_event_groups,
    extract_1x2_from_flat_events,
    is_complete_1x2,
)
from kenyan.parsers.onexbet_parser import iter_events, parse_all_markets
from kenyan.workers.base import BaseKenyanWorker, Diagnostics, apply_catalogue_status
from kenyan.workers.poll_combine import map_polls
from kenyan.workers.vzip_pages import fetch_vzip_all

# games1x2 count=1000 / skip= returns HTTP 400. count=250 is the
# proven games1x2 window; Get1x2_VZip is then walked with `after`.
_GAMES_QUERY = "cfView=3&count=250&fcountry=87&gr=656&grMode=4&lng=en&ref=61"
_FOOTBALL_QUERY = _GAMES_QUERY
LIVE_URL = (
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_FOOTBALL_QUERY}&selectedMs=2.1"
)
PREMATCH_URL = (
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_FOOTBALL_QUERY}&selectedMs=2.1"
)
LIVE_EXTRA_URLS = (
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=1.4,2.4,10.4",
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=1.3,2.3,10.3",
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=2.6",
    "https://1xbet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=1&count=400&lng=en&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=3&count=400&lng=en&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=4&count=400&lng=en&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=6&count=400&lng=en&mode=4&country=87&getEmpty=true",
)
PREMATCH_EXTRA_URLS = (
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=1.4,2.4,10.4",
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=2.3,2.6",
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_GAMES_QUERY}&selectedMs=2.6",
    "https://1xbet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=1&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=3&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=4&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
    "https://1xbet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=6&count=400&lng=en&tf=2200000&tz=3&mode=4&country=87&getEmpty=true",
)


def _poll_one(url: str, status: str):
    if "Get1x2_VZip" in url:
        max_pages = (
            KENYAN_VZIP_MAX_PAGES if status == LIVE else KENYAN_PREMATCH_RUNAWAY_PAGES
        )
        envelope, fetch_result = fetch_vzip_all(url, max_pages=max_pages)
        json_body = envelope
    else:
        fetch_result = fetch_json(url)
        json_body = fetch_result.json_body
    if not fetch_result.ok:
        failed = Diagnostics(
            endpoint_status="http_error" if fetch_result.status_code else "exception",
            http_status_code=fetch_result.status_code,
            content_type=fetch_result.content_type,
            response_size_bytes=fetch_result.response_size_bytes,
            parser_error=fetch_result.error,
            elapsed_seconds=fetch_result.elapsed_seconds,
            acquired_at=time.time(),
            pages_fetched=getattr(fetch_result, "pages_fetched", 1),
            page_cap_hit=getattr(fetch_result, "page_cap_hit", False),
            snapshot_complete=getattr(fetch_result, "snapshot_complete", True),
        )
        copy_cache_headers(failed, fetch_result)
        return [], apply_catalogue_status(failed)

    raw_events = iter_events(json_body)
    football_events = 0
    one_x_two_events = 0
    for event in raw_events:
        sport_id = (event.get("sport") or {}).get("id") if "eventGroups" in event else event.get("SI")
        if sport_id != 1:
            continue
        football_events += 1
        prices = (
            extract_1x2_from_event_groups(event.get("eventGroups"))
            if "eventGroups" in event
            else extract_1x2_from_flat_events(event.get("E"))
        )
        if is_complete_1x2(prices):
            one_x_two_events += 1

    try:
        matches = parse_all_markets(json_body, status=status)
        parser_error = None
    except Exception as exc:  # noqa: BLE001
        matches = []
        parser_error = f"{type(exc).__name__}: {exc}"

    diagnostics = Diagnostics(
        endpoint_status="ok" if parser_error is None else "bad_payload",
        http_status_code=fetch_result.status_code,
        content_type=fetch_result.content_type,
        response_size_bytes=fetch_result.response_size_bytes,
        events_discovered=len(raw_events),
        football_events=football_events,
        one_x_two_events=one_x_two_events,
        valid_normalized_events=len(matches),
        parser_error=parser_error,
        elapsed_seconds=fetch_result.elapsed_seconds,
        acquired_at=time.time(),
        pages_fetched=getattr(fetch_result, "pages_fetched", 1),
        page_cap_hit=getattr(fetch_result, "page_cap_hit", False),
        snapshot_complete=getattr(fetch_result, "snapshot_complete", True),
        unique_event_ids=getattr(fetch_result, "unique_event_ids", 0) or len(raw_events),
        duplicate_events=getattr(fetch_result, "duplicate_events", 0) or 0,
    )
    copy_cache_headers(diagnostics, fetch_result)
    return matches, apply_catalogue_status(diagnostics)


def _poll(urls, status: str):
    return map_polls(_poll_one, urls, status)


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{ONEXBET}_live",
        poll_fn=lambda: _poll((LIVE_URL,) + LIVE_EXTRA_URLS, "LIVE"),
        poll_interval_seconds=KENYAN_LIVE_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_LIVE_STALE_AFTER_SECONDS,
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{ONEXBET}_prematch",
        poll_fn=lambda: _poll((PREMATCH_URL,) + PREMATCH_EXTRA_URLS, "PREMATCH"),
        poll_interval_seconds=KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    )
