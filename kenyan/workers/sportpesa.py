"""
Persistent SportPesa workers (one for LIVE, one for PREMATCH).

LIVE is a two-step flow per poll cycle (discover -> build dynamic
markets URL -> fetch markets -> parse), exactly as required: the event
ids are NEVER hardcoded, they come fresh from the discovery call every
cycle. Both HTTP calls together still complete well within the 5s
poll interval for the handful of currently-live football events, so
this remains "one persistent worker, polling every 5 seconds" rather
than spinning up anything new per cycle.

PREMATCH walks `/api/todays/1/games` (embedded 1X2 odds) until a short
or empty page. That endpoint is football and Kenya-today scoped by
the API; extra sports are not invented here. There is no catalogue
page ceiling -- only runaway-loop protection.

ANTI-BOT CHALLENGE: both `www.ke.sportpesa.com` and `www.sportpesa.com`
currently serve an Imperva "Challenge Validation" HTML page to plain
HTTP GETs (HTTP 200, non-JSON). This module does not reuse OnWin/
BetKanyon ZenRows sessions. A challenge is recorded as a failed
acquisition (`looks_like_bot_challenge`) and health becomes DEGRADED
after the Kenyan consecutive-failure threshold — never RUNNING just
because the poll thread is alive, and never by fabricating odds.
"""
import time

from kenyan.config import (
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_LIVE_STALE_AFTER_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT,
    KENYAN_SPORTPESA_LIVE_MAX_PAGES,
    SPORTPESA,
)
from kenyan.http_utils import copy_cache_headers, fetch_json, looks_like_bot_challenge
from kenyan.parsers.sportpesa_parser import (
    build_live_discovery_url,
    build_live_markets_url,
    build_todays_games_url,
    extract_live_football_events,
    parse_live_markets,
    parse_todays_games,
)
from kenyan.workers.base import BaseKenyanWorker, Diagnostics, apply_catalogue_status

# Browser and ke.sportpesa.com requests use pag_count=15. Requesting a
# larger count while advancing pag_min as a page index can skip events
# if the API pages by the requested size but returns fewer rows.
PREMATCH_PAGE_COUNT = 15
PREMATCH_MAX_PAGES_PER_CYCLE = KENYAN_PREMATCH_RUNAWAY_PAGES
LIVE_DISCOVERY_LIMIT = KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT
LIVE_DISCOVERY_MAX_PAGES = KENYAN_SPORTPESA_LIVE_MAX_PAGES

# Browser-like Origin/Referer only — never cookies/tokens. Direct HTTP
# to both www.sportpesa.com and ke.sportpesa.com currently returns an
# Imperva "Challenge Validation" HTML page (HTTP 200, not JSON); that
# is recorded as a failed acquisition, not RUNNING.
SPORTPESA_HEADERS = {
    "Origin": "https://www.sportpesa.com",
    "Referer": "https://www.sportpesa.com/",
}


def _fetch(url, retries=0):
    if retries:
        return fetch_json(url, headers=SPORTPESA_HEADERS, retries=retries)
    return fetch_json(url, headers=SPORTPESA_HEADERS)


def _blocked_diagnostics(fetch_result) -> Diagnostics:
    error = fetch_result.error
    if looks_like_bot_challenge(fetch_result):
        error = "blocked by anti-bot challenge (non-JSON challenge page returned)"

    return copy_cache_headers(
        Diagnostics(
            endpoint_status="http_error" if fetch_result.status_code else "exception",
            http_status_code=fetch_result.status_code,
            content_type=fetch_result.content_type,
            response_size_bytes=fetch_result.response_size_bytes,
            parser_error=error,
            elapsed_seconds=fetch_result.elapsed_seconds,
            acquired_at=time.time(),
        ),
        fetch_result,
    )


def _poll_live():
    discovered_events = []
    seen_ids = set()
    pages_fetched = 0
    total_size = 0
    total_elapsed = 0.0
    last_ok = None
    snapshot_complete = True
    page_cap_hit = False

    for page in range(LIVE_DISCOVERY_MAX_PAGES):
        offset = page * LIVE_DISCOVERY_LIMIT
        discovery_result = _fetch(
            build_live_discovery_url(limit=LIVE_DISCOVERY_LIMIT, offset=offset)
        )
        pages_fetched += 1
        total_elapsed += discovery_result.elapsed_seconds
        total_size += discovery_result.response_size_bytes
        if not discovery_result.ok:
            if page == 0:
                return [], _blocked_diagnostics(discovery_result)
            snapshot_complete = False
            break
        last_ok = discovery_result
        page_events = extract_live_football_events(discovery_result.json_body)
        raw = discovery_result.json_body.get("events") if isinstance(discovery_result.json_body, dict) else []
        raw_count = len(raw) if isinstance(raw, list) else 0
        added = 0
        for event in page_events:
            event_id = event.get("event_id")
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            discovered_events.append(event)
            added += 1
        if raw_count < LIVE_DISCOVERY_LIMIT:
            break
        if added == 0:
            break
    else:
        page_cap_hit = True
        snapshot_complete = False

    if not discovered_events:
        return [], Diagnostics(
            endpoint_status="ok",
            http_status_code=last_ok.status_code if last_ok is not None else None,
            content_type=last_ok.content_type if last_ok is not None else None,
            response_size_bytes=total_size,
            events_discovered=0,
            football_events=0,
            elapsed_seconds=total_elapsed,
            acquired_at=time.time(),
            pages_fetched=pages_fetched,
            page_cap_hit=page_cap_hit,
            snapshot_complete=snapshot_complete,
        )

    event_ids = [event["event_id"] for event in discovered_events]
    markets_result = _fetch(build_live_markets_url(event_ids))
    pages_fetched += 1
    total_elapsed += markets_result.elapsed_seconds
    total_size += markets_result.response_size_bytes

    if not markets_result.ok:
        blocked = _blocked_diagnostics(markets_result)
        blocked.pages_fetched = pages_fetched
        blocked.page_cap_hit = page_cap_hit
        blocked.snapshot_complete = False
        return [], blocked

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
        response_size_bytes=total_size,
        events_discovered=len(discovered_events),
        football_events=len(discovered_events),
        one_x_two_events=len((markets_result.json_body or {}).get("markets") or []),
        valid_normalized_events=len(matches),
        parser_error=parser_error,
        elapsed_seconds=total_elapsed,
        acquired_at=time.time(),
        pages_fetched=pages_fetched,
        page_cap_hit=page_cap_hit,
        snapshot_complete=snapshot_complete and parser_error is None,
    )
    copy_cache_headers(diagnostics, markets_result)

    return matches, diagnostics


def _poll_prematch():
    all_matches = []
    total_events = 0
    total_football = 0
    total_size = 0
    total_elapsed = 0.0
    last_status_code = None
    last_content_type = None

    pages_fetched = 0
    snapshot_complete = True
    page_cap_hit = False
    seen_ids = set()
    duplicate_events = 0
    observed_page_size = None
    terminal_reason = "empty_page"
    first_cursor = None
    page = 1
    while page <= PREMATCH_MAX_PAGES_PER_CYCLE:
        url = build_todays_games_url(page_min=page, page_count=PREMATCH_PAGE_COUNT)
        result = _fetch(url, retries=2)
        pages_fetched += 1

        if not result.ok:
            if page == 1:
                blocked = _blocked_diagnostics(result)
                blocked.pages_fetched = pages_fetched
                blocked.snapshot_complete = False
                blocked.terminal_reason = "http_error"
                return [], apply_catalogue_status(blocked)
            snapshot_complete = False
            terminal_reason = "http_error"
            break  # keep whatever earlier pages already produced

        last_status_code = result.status_code
        last_content_type = result.content_type
        total_size += result.response_size_bytes
        total_elapsed += result.elapsed_seconds

        page_games = result.json_body or []
        if not isinstance(page_games, list):
            page_games = []
        total_events += len(page_games)
        total_football += sum(
            1 for g in page_games if (g.get("sport") or {}).get("id") == 1
        )
        added = 0
        for game in page_games:
            if not isinstance(game, dict):
                continue
            event_id = game.get("id") or game.get("externalId")
            if event_id in seen_ids:
                duplicate_events += 1
                continue
            seen_ids.add(event_id)
            added += 1

        if first_cursor is None:
            first_cursor = str(page)

        try:
            all_matches.extend(parse_todays_games(page_games))
        except Exception as exc:  # noqa: BLE001
            return [], apply_catalogue_status(
                Diagnostics(
                    endpoint_status="bad_payload",
                    http_status_code=result.status_code,
                    content_type=result.content_type,
                    response_size_bytes=total_size,
                    events_discovered=total_events,
                    football_events=total_football,
                    parser_error=f"{type(exc).__name__}: {exc}",
                    elapsed_seconds=total_elapsed,
                    acquired_at=time.time(),
                    pages_fetched=pages_fetched,
                    snapshot_complete=False,
                    unique_event_ids=len(seen_ids),
                    duplicate_events=duplicate_events,
                    terminal_reason="parse_error",
                    first_cursor=first_cursor,
                    last_cursor=str(page),
                )
            )

        if not page_games:
            terminal_reason = "empty_page"
            break
        if observed_page_size is None:
            observed_page_size = len(page_games)
        if added == 0:
            snapshot_complete = False
            terminal_reason = "zero_new_ids"
            break
        if len(page_games) < observed_page_size:
            # Stop on a page shorter than the first observed page, not
            # on a page shorter than the requested pag_count.
            terminal_reason = "short_page"
            break
        page += 1
    else:
        page_cap_hit = True
        snapshot_complete = False
        terminal_reason = "runaway_guard"

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
        pages_fetched=pages_fetched,
        page_cap_hit=page_cap_hit,
        snapshot_complete=snapshot_complete,
        unique_event_ids=len(seen_ids),
        duplicate_events=duplicate_events,
        terminal_reason=terminal_reason,
        first_cursor=first_cursor,
        last_cursor=str(page),
    )

    return all_matches, apply_catalogue_status(diagnostics)


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{SPORTPESA}_live",
        poll_fn=_poll_live,
        poll_interval_seconds=KENYAN_LIVE_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_LIVE_STALE_AFTER_SECONDS,
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{SPORTPESA}_prematch",
        poll_fn=_poll_prematch,
        poll_interval_seconds=KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    )
