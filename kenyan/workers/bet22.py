"""
Persistent 22Bet workers (one for LIVE, one for PREMATCH).

Deliberately never queries GetSportsShortZip -- see
kenyan/parsers/bet22_parser.py for why that endpoint is navigation
data only and unnecessary for this module's purposes.
"""
import time

from kenyan.config import (
    BET22,
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
)
from kenyan.parsers._common_1x2 import extract_1x2_from_flat_events, is_complete_1x2
from kenyan.parsers.bet22_parser import parse_all_markets
from kenyan.workers.base import BaseKenyanWorker, Diagnostics
from kenyan.workers.poll_combine import map_polls
from kenyan.workers.vzip_pages import fetch_vzip_all

LIVE_URL = (
    "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip"
    "?sports=1&count=400&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true"
)
PREMATCH_URL = (
    "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip"
    "?sports=1&count=400&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216"
)

LIVE_EXTRA_URLS = (
    "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=4&count=400&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
    "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=3&count=400&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
    "https://22bet.co.ke/service-api/LiveFeed/Get1x2_VZip?sports=6&count=400&lng=en_GB&gr=216&mode=4&country=87&partner=151&getEmpty=true",
)
PREMATCH_EXTRA_URLS = (
    "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=4&count=400&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216",
    "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=3&count=400&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216",
    "https://22bet.co.ke/service-api/LineFeed/Get1x2_VZip?sports=6&count=400&lng=en_GB&tz=3&mode=4&country=87&partner=151&getEmpty=true&gr=216",
)


def _poll_one(url: str, status: str):
    envelope, fetch_result = fetch_vzip_all(url)
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

    raw_events = (envelope or {}).get("Value") or []
    football_events = 0
    one_x_two_events = 0
    for event in raw_events:
        if event.get("SI") != 1:
            continue
        football_events += 1
        if is_complete_1x2(extract_1x2_from_flat_events(event.get("E"))):
            one_x_two_events += 1

    try:
        matches = parse_all_markets(envelope, status=status)
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
    return map_polls(_poll_one, urls, status)


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BET22}_live",
        poll_fn=lambda: _poll((LIVE_URL,) + LIVE_EXTRA_URLS, "LIVE"),
        poll_interval_seconds=KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BET22}_prematch",
        poll_fn=lambda: _poll((PREMATCH_URL,) + PREMATCH_EXTRA_URLS, "PREMATCH"),
        poll_interval_seconds=KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    )
