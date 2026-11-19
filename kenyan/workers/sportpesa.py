"""
Persistent SportPesa workers (one for LIVE, one for PREMATCH).

LIVE is a two-step flow per poll cycle (discover -> build dynamic
markets URL -> fetch markets -> parse). Event ids come from the
discovery call every cycle. LIVE is unchanged by the prematch session.

PREMATCH opens one HTTP session, GETs the public homepage so the site
can set its own cookies, then reuses that session for the catalogue
and for `/api/games/markets`. `pag_min` is the 1-based item index.
Completeness comes from `Content-Range: start-end/total` (0-based,
inclusive). The next `pag_min` is `end + 2`. There is no page, offset,
or skip parameter.

www.ke.sportpesa.com returns HTTP 403 Access Denied to this client and
sets no cookies. This module does not bypass that response. The same
API paths on www.sportpesa.com return JSON after the homepage GET.
HTTP 200/206 HTML that is not JSON is a source failure, not an empty
catalogue. A JSON body is accepted even when Content-Type is text/html.
"""
import time

import requests

from kenyan.config import (
    KENYAN_HTTP_TIMEOUT_SECONDS,
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_LIVE_STALE_AFTER_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT,
    KENYAN_SPORTPESA_LIVE_MAX_PAGES,
    KENYAN_USER_AGENT,
    SPORTPESA,
)
from kenyan.http_utils import (
    FetchResult,
    copy_cache_headers,
    fetch_json,
    looks_like_bot_challenge,
)
from kenyan.parsers.sportpesa_parser import (
    SPORTPESA_BASE_URL,
    assemble_prematch_matches,
    build_live_discovery_url,
    build_live_markets_url,
    build_prematch_markets_url,
    build_todays_games_url,
    extract_live_football_events,
    looks_like_live_markets_payload,
    parse_content_range,
    parse_live_markets,
)
from kenyan.workers.base import BaseKenyanWorker, Diagnostics, apply_catalogue_status

# Verified catalogue page size. pag_min steps by the number of rows
# returned (Content-Range end + 2), not by 1.
PREMATCH_PAGE_COUNT = 15
PREMATCH_MARKETS_BATCH = 15
PREMATCH_REQUEST_PACE_SECONDS = 0.05
PREMATCH_MAX_PAGES_PER_CYCLE = KENYAN_PREMATCH_RUNAWAY_PAGES
LIVE_DISCOVERY_LIMIT = KENYAN_SPORTPESA_LIVE_DISCOVERY_LIMIT
LIVE_DISCOVERY_MAX_PAGES = KENYAN_SPORTPESA_LIVE_MAX_PAGES

# LIVE headers. Prematch adds the XHR headers verified on the site.
SPORTPESA_HEADERS = {
    "Origin": "https://www.sportpesa.com",
    "Referer": "https://www.sportpesa.com/",
}
PREMATCH_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.sportpesa.com",
    "Referer": "https://www.sportpesa.com/",
    "X-Requested-With": "XMLHttpRequest",
    "X-App-Timezone": "Africa/Nairobi",
}


def _fetch(url, retries=0, session=None, headers=None):
    kwargs = {"headers": headers or SPORTPESA_HEADERS}
    if retries:
        kwargs["retries"] = retries
    if session is not None:
        kwargs["session"] = session
    return fetch_json(url, **kwargs)


def establish_prematch_session():
    """
    Open one session and load the public homepage.

    Cookies set by that response stay on the session. Their values are
    not read or logged. A challenge page or an HTTP error is a failed
    session, not an empty catalogue.
    """
    session = requests.Session()
    home = f"{SPORTPESA_BASE_URL}/"
    start = time.monotonic()
    try:
        response = session.get(
            home,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": KENYAN_USER_AGENT,
            },
            timeout=KENYAN_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return None, FetchResult(
            url=home,
            ok=False,
            status_code=None,
            content_type=None,
            response_size_bytes=0,
            elapsed_seconds=time.monotonic() - start,
            error=f"{type(exc).__name__}: {exc}",
        )

    text = response.text or ""
    content_type = response.headers.get("content-type")
    result = FetchResult(
        url=home,
        ok=response.status_code < 400,
        status_code=response.status_code,
        content_type=content_type,
        response_size_bytes=len(response.content or b""),
        elapsed_seconds=time.monotonic() - start,
        text_body=text[:2000],
        error=None if response.status_code < 400 else f"HTTP {response.status_code}",
    )
    if response.status_code >= 400 or looks_like_bot_challenge(result):
        result.ok = False
        if looks_like_bot_challenge(result):
            result.error = "blocked by anti-bot challenge (non-JSON challenge page returned)"
        return None, result
    return session, None


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


def _prematch_failure(result, *, pages_fetched):
    blocked = _blocked_diagnostics(result)
    if not looks_like_bot_challenge(result):
        body = (result.text_body or "").lstrip()
        content_type = (result.content_type or "").lower()
        if body.startswith("<") or ("html" in content_type and not result.looks_like_json):
            blocked.parser_error = "non-JSON HTML response"
            blocked.endpoint_status = "http_error"
        elif result.status_code is not None and result.status_code < 400:
            blocked.endpoint_status = "bad_payload"
    blocked.pages_fetched = pages_fetched
    blocked.snapshot_complete = False
    blocked.terminal_reason = (
        "http_error" if blocked.endpoint_status == "http_error" else "bad_payload"
    )
    return [], apply_catalogue_status(blocked)


def _pace():
    if PREMATCH_REQUEST_PACE_SECONDS > 0:
        time.sleep(PREMATCH_REQUEST_PACE_SECONDS)


def _poll_prematch():
    session, session_failure = establish_prematch_session()
    if session_failure is not None:
        failed, diagnostics = _prematch_failure(session_failure, pages_fetched=0)
        diagnostics.terminal_reason = "session_failed"
        return failed, apply_catalogue_status(diagnostics)

    games = []
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
    terminal_reason = "empty_page"
    first_cursor = None
    source_total = None
    pag_min = 1
    last_cursor = "1"

    while True:
        if pages_fetched >= PREMATCH_MAX_PAGES_PER_CYCLE:
            page_cap_hit = True
            snapshot_complete = False
            terminal_reason = "runaway_guard"
            break
        if pages_fetched:
            _pace()
        url = build_todays_games_url(page_min=pag_min, page_count=PREMATCH_PAGE_COUNT)
        result = _fetch(url, retries=2, session=session, headers=PREMATCH_HEADERS)
        pages_fetched += 1
        last_cursor = str(pag_min)
        if first_cursor is None:
            first_cursor = str(pag_min)

        if not result.ok:
            if not games:
                return _prematch_failure(result, pages_fetched=pages_fetched)
            snapshot_complete = False
            body = (result.text_body or "").lstrip()
            if body.startswith("<") or looks_like_bot_challenge(result):
                terminal_reason = "non_json_html"
            else:
                terminal_reason = "http_error"
            break

        last_status_code = result.status_code
        last_content_type = result.content_type
        total_size += result.response_size_bytes
        total_elapsed += result.elapsed_seconds

        page_games = result.json_body
        if not isinstance(page_games, list):
            if not games:
                return [], apply_catalogue_status(
                    Diagnostics(
                        endpoint_status="bad_payload",
                        http_status_code=result.status_code,
                        content_type=result.content_type,
                        response_size_bytes=total_size,
                        parser_error="expected a PREMATCH game list",
                        elapsed_seconds=total_elapsed,
                        acquired_at=time.time(),
                        pages_fetched=pages_fetched,
                        snapshot_complete=False,
                        terminal_reason="bad_payload",
                        first_cursor=first_cursor,
                        last_cursor=last_cursor,
                    )
                )
            snapshot_complete = False
            terminal_reason = "bad_payload"
            break

        total_events += len(page_games)
        span = parse_content_range(result.content_range)
        if span is not None:
            _start, end, total = span
            source_total = total
            next_min = end + 2
            page_complete = end + 1 >= total
        else:
            next_min = pag_min + len(page_games)
            page_complete = len(page_games) < PREMATCH_PAGE_COUNT

        added = 0
        for game in page_games:
            if not isinstance(game, dict):
                continue
            sport = game.get("sport") or {}
            if isinstance(sport, dict) and sport.get("id") == 1:
                total_football += 1
            event_id = game.get("id")
            if event_id in (None, ""):
                games.append(game)
                continue
            if event_id in seen_ids:
                duplicate_events += 1
                continue
            seen_ids.add(event_id)
            games.append(game)
            added += 1

        if not page_games:
            terminal_reason = "empty_page"
            if span is not None and end + 1 < total:
                snapshot_complete = False
            else:
                snapshot_complete = True
            break
        if added == 0:
            snapshot_complete = False
            terminal_reason = "zero_new_ids"
            break
        if page_complete:
            terminal_reason = "content_range" if span is not None else "short_page"
            snapshot_complete = True
            break
        if next_min <= pag_min:
            snapshot_complete = False
            terminal_reason = "pagination_stalled"
            break
        pag_min = next_min

    markets_payload = {}
    if games and snapshot_complete:
        event_ids = [game.get("id") for game in games if game.get("id") not in (None, "")]
        markets_ok = True
        for offset in range(0, len(event_ids), PREMATCH_MARKETS_BATCH):
            if offset:
                _pace()
            batch = event_ids[offset : offset + PREMATCH_MARKETS_BATCH]
            markets_result = _fetch(
                build_prematch_markets_url(batch),
                retries=2,
                session=session,
                headers=PREMATCH_HEADERS,
            )
            total_size += markets_result.response_size_bytes
            total_elapsed += markets_result.elapsed_seconds
            body = markets_result.json_body
            if (
                not markets_result.ok
                or not isinstance(body, dict)
                or looks_like_live_markets_payload(body)
            ):
                markets_ok = False
                break
            markets_payload.update(body)
        if not markets_ok:
            snapshot_complete = False
            terminal_reason = "markets_incomplete"

    try:
        matches = assemble_prematch_matches(games, markets_payload or None)
    except Exception as exc:  # noqa: BLE001
        return [], apply_catalogue_status(
            Diagnostics(
                endpoint_status="bad_payload",
                http_status_code=last_status_code,
                content_type=last_content_type,
                response_size_bytes=total_size,
                events_discovered=total_events,
                football_events=total_football,
                parser_error=f"{type(exc).__name__}: {exc}",
                elapsed_seconds=total_elapsed,
                acquired_at=time.time(),
                pages_fetched=pages_fetched,
                snapshot_complete=False,
                source_total=source_total,
                unique_event_ids=len(seen_ids),
                duplicate_events=duplicate_events,
                terminal_reason="parse_error",
                first_cursor=first_cursor,
                last_cursor=last_cursor,
            )
        )

    one_x_two = sum(1 for match in matches if match.market == "1X2")
    diagnostics = Diagnostics(
        endpoint_status="ok",
        http_status_code=last_status_code,
        content_type=last_content_type,
        response_size_bytes=total_size,
        events_discovered=total_events,
        football_events=total_football,
        one_x_two_events=one_x_two,
        valid_normalized_events=len(matches),
        elapsed_seconds=total_elapsed,
        acquired_at=time.time(),
        pages_fetched=pages_fetched,
        page_cap_hit=page_cap_hit,
        snapshot_complete=snapshot_complete,
        source_total=source_total,
        unique_event_ids=len(seen_ids),
        duplicate_events=duplicate_events,
        terminal_reason=terminal_reason,
        first_cursor=first_cursor,
        last_cursor=last_cursor,
    )
    return matches, apply_catalogue_status(diagnostics)


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
