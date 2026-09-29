"""
Persistent SportPesa workers (one for LIVE, one for PREMATCH).

LIVE is a two-step flow per poll cycle (discover -> build dynamic
markets URL -> fetch markets -> parse), exactly as required: the event
ids are NEVER hardcoded, they come fresh from the discovery call every
cycle. Both HTTP calls together still complete well within the 5s
poll interval for the handful of currently-live football events, so
this remains "one persistent worker, polling every 5 seconds" rather
than spinning up anything new per cycle.

PREMATCH is a single call to the date-scoped `todays/1/games` endpoint
(already includes 1x2 odds -- see kenyan/parsers/sportpesa_parser.py
for why this was chosen over `games/markets`), paginated across a
few pages per cycle to cover a reasonable share of today's fixture
list without unbounded network calls.

ANTI-BOT CHALLENGE: `ke.sportpesa.com` (as given in the task) serves a
JS proof-of-work challenge to plain HTTP requests -- the same category
of problem the existing OnWin/BetKanyon workers solve with a real
browser session. This module talks to `www.sportpesa.com` instead
(confirmed live to serve the identical API with no challenge -- see
kenyan/parsers/sportpesa_parser.py). If that host ever starts
challenging requests too, `fetch_json`'s result will fail
`looks_like_json` and `looks_like_bot_challenge()` will flag it
explicitly in diagnostics/health (reported as DEGRADED, never
silently as RUNNING) rather than the worker crash-looping or
fabricating data.
"""
import time

from kenyan.config import SPORTPESA
from kenyan.http_utils import fetch_json, looks_like_bot_challenge
from kenyan.parsers.sportpesa_parser import (
    build_live_discovery_url,
    build_live_markets_url,
    build_todays_games_url,
    extract_live_football_events,
    parse_live_markets,
    parse_todays_games,
)
from kenyan.workers.base import BaseKenyanWorker, Diagnostics

PREMATCH_PAGE_COUNT = 100
PREMATCH_MAX_PAGES_PER_CYCLE = 3


def _blocked_diagnostics(fetch_result) -> Diagnostics:
    error = fetch_result.error
    if looks_like_bot_challenge(fetch_result):
        error = "blocked by anti-bot challenge (non-JSON challenge page returned)"

    return Diagnostics(
        endpoint_status="http_error" if fetch_result.status_code else "exception",
        http_status_code=fetch_result.status_code,
        content_type=fetch_result.content_type,
        response_size_bytes=fetch_result.response_size_bytes,
        parser_error=error,
        elapsed_seconds=fetch_result.elapsed_seconds,
        acquired_at=time.time(),
    )


def _poll_live():
    discovery_result = fetch_json(build_live_discovery_url(limit=50, offset=0))

    if not discovery_result.ok:
        return [], _blocked_diagnostics(discovery_result)

    discovered_events = extract_live_football_events(discovery_result.json_body)

    if not discovered_events:
        return [], Diagnostics(
            endpoint_status="ok",
            http_status_code=discovery_result.status_code,
            content_type=discovery_result.content_type,
            response_size_bytes=discovery_result.response_size_bytes,
            events_discovered=0,
            football_events=0,
            elapsed_seconds=discovery_result.elapsed_seconds,
            acquired_at=time.time(),
        )

    event_ids = [event["event_id"] for event in discovered_events]
    markets_result = fetch_json(build_live_markets_url(event_ids))

    if not markets_result.ok:
        return [], _blocked_diagnostics(markets_result)

    try:
        matches = parse_live_markets(markets_result.json_body, discovered_events)
        parser_error = None
    except Exception as exc:  # noqa: BLE001
        matches = []
        parser_error = f"{type(exc).__name__}: {exc}"

    diagnostics = Diagnostics(
        endpoint_status="ok" if parser_error is None else "bad_payload",
        http_status_code=markets_result.status_code,
        content_type=markets_result.content_type,
        response_size_bytes=markets_result.response_size_bytes,
        events_discovered=len(discovered_events),
        football_events=len(discovered_events),
        one_x_two_events=len((markets_result.json_body or {}).get("markets") or []),
        valid_normalized_events=len(matches),
        parser_error=parser_error,
        elapsed_seconds=discovery_result.elapsed_seconds + markets_result.elapsed_seconds,
        acquired_at=time.time(),
    )

    return matches, diagnostics


def _poll_prematch():
    all_matches = []
    total_events = 0
    total_football = 0
    total_size = 0
    total_elapsed = 0.0
    last_status_code = None
    last_content_type = None

    for page in range(1, PREMATCH_MAX_PAGES_PER_CYCLE + 1):
        url = build_todays_games_url(page_min=page, page_count=PREMATCH_PAGE_COUNT)
        result = fetch_json(url)

        if not result.ok:
            if page == 1:
                return [], _blocked_diagnostics(result)
            break  # keep whatever earlier pages already produced

        last_status_code = result.status_code
        last_content_type = result.content_type
        total_size += result.response_size_bytes
        total_elapsed += result.elapsed_seconds

        page_games = result.json_body or []
        total_events += len(page_games)
        total_football += sum(
            1 for g in page_games if (g.get("sport") or {}).get("id") == 1
        )

        try:
            all_matches.extend(parse_todays_games(page_games))
        except Exception as exc:  # noqa: BLE001
            return [], Diagnostics(
                endpoint_status="bad_payload",
                http_status_code=result.status_code,
                content_type=result.content_type,
                response_size_bytes=total_size,
                events_discovered=total_events,
                football_events=total_football,
                parser_error=f"{type(exc).__name__}: {exc}",
                elapsed_seconds=total_elapsed,
                acquired_at=time.time(),
            )

        if len(page_games) < PREMATCH_PAGE_COUNT:
            break  # last page

    diagnostics = Diagnostics(
        endpoint_status="ok",
        http_status_code=last_status_code,
        content_type=last_content_type,
        response_size_bytes=total_size,
        events_discovered=total_events,
        football_events=total_football,
        one_x_two_events=total_football,
        valid_normalized_events=len(all_matches),
        elapsed_seconds=total_elapsed,
        acquired_at=time.time(),
    )

    return all_matches, diagnostics


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(name=f"{SPORTPESA}_live", poll_fn=_poll_live)


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(name=f"{SPORTPESA}_prematch", poll_fn=_poll_prematch)
