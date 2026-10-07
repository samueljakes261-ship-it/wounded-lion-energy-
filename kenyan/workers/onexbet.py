"""
Persistent 1xBet workers (one for LIVE, one for PREMATCH).
"""
import time

from kenyan.config import ONEXBET
from kenyan.http_utils import fetch_json
from kenyan.parsers._common_1x2 import (
    extract_1x2_from_event_groups,
    extract_1x2_from_flat_events,
    is_complete_1x2,
)
from kenyan.parsers.onexbet_parser import iter_events, parse_all_markets
from kenyan.workers.base import BaseKenyanWorker, Diagnostics

LIVE_URL = (
    "https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2"
    "?cfView=3&count=50&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.1"
)
PREMATCH_URL = (
    "https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2"
    "?cfView=3&count=50&fcountry=87&gr=656&grMode=4&lng=en&ref=61&selectedMs=2.1"
)

# Extra sports use a larger count because count=40 is a truncated window.
_EXTRA_QUERY = "cfView=3&count=250&fcountry=87&gr=656&grMode=4&lng=en&ref=61"
LIVE_EXTRA_URLS = (
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=1.4,2.4,10.4",
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=1.3,2.3,10.3",
    f"https://1xbet.co.ke/service-api/main-live-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=2.6",
)
PREMATCH_EXTRA_URLS = (
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=1.4,2.4,10.4",
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=2.3,2.6",
    f"https://1xbet.co.ke/service-api/main-line-feed/v3/games1x2?{_EXTRA_QUERY}&selectedMs=2.6",
)


def _poll_one(url: str, status: str):
    fetch_result = fetch_json(url)
    if not fetch_result.ok:
        return [], Diagnostics(
            endpoint_status="http_error" if fetch_result.status_code else "exception",
            http_status_code=fetch_result.status_code,
            content_type=fetch_result.content_type,
            response_size_bytes=fetch_result.response_size_bytes,
            parser_error=fetch_result.error,
            elapsed_seconds=fetch_result.elapsed_seconds,
            acquired_at=time.time(),
        )

    raw_events = iter_events(fetch_result.json_body)
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
        matches = parse_all_markets(fetch_result.json_body, status=status)
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
    )
    return matches, diagnostics


def _poll(urls, status: str):
    combined = []
    seen = set()
    last_diagnostics = None
    for url in urls:
        matches, diagnostics = _poll_one(url, status)
        last_diagnostics = diagnostics
        for match in matches:
            key = (
                match.event_id,
                match.market,
                match.period,
                match.line,
                match.cluster_id,
            )
            if key in seen:
                continue
            seen.add(key)
            combined.append(match)
    if last_diagnostics is not None:
        last_diagnostics.valid_normalized_events = len(combined)
        last_diagnostics.events_discovered = max(
            last_diagnostics.events_discovered, len(combined)
        )
    return combined, last_diagnostics or Diagnostics(endpoint_status="exception")


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{ONEXBET}_live",
        poll_fn=lambda: _poll((LIVE_URL,) + LIVE_EXTRA_URLS, "LIVE"),
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{ONEXBET}_prematch",
        poll_fn=lambda: _poll((PREMATCH_URL,) + PREMATCH_EXTRA_URLS, "PREMATCH"),
    )
