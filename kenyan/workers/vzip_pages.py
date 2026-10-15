"""
Walk 1xCorp Get1x2_VZip catalogues.

games1x2 `count=1000` and `skip=` return HTTP 400. Asking for
`count=400` still returns 50 events (verified live on 1xBet and 22Bet).

LIVE still uses `after=<last event I>`. On the Kenyan 1xBet/22Bet
hosts that extra query key currently returns HTTP 406, so a LIVE walk
stops incomplete after the first 50-event window. LIVE pagination is
intentionally unchanged.

PREMATCH cannot use `after=` (same 406). The working LineFeed contract
is GetChampsZip?sport=<id> then Get1x2_VZip?champs=<LI> without
`sports=` or `after=`. Each championship is still capped at 50 events;
a 50-row champ whose advertised GC is higher is incomplete.
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kenyan.config import KENYAN_VZIP_MAX_PAGES
from kenyan.http_utils import FetchResult, copy_cache_headers, fetch_json

PAGE_COUNT = 400
MAX_PAGES = KENYAN_VZIP_MAX_PAGES
CHAMP_EVENT_CAP = 50
CHAMP_CONCURRENCY = 4
# Kenyan 1xCorp gateways 406 when allowed keys appear in the wrong
# order. `sport` / `champs` must lead the query string.
_CHAMP_LIST_KEYS = ("lng", "tf", "tz", "country", "partner")
_CHAMP_EVENT_KEYS = ("lng", "tf", "tz", "mode", "country", "partner", "getEmpty", "gr")


def with_query(url: str, **updates) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in updates.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def fetch_vzip_all(
    url: str,
    *,
    fetch=None,
    page_count: int = PAGE_COUNT,
    max_pages: int = MAX_PAGES,
    retries: int = 0,
):
    if fetch is None:
        if retries:
            fetch = lambda page_url: fetch_json(page_url, retries=retries)  # noqa: E731
        else:
            fetch = fetch_json
    combined = []
    seen = set()
    last = None
    after = None
    first_cursor = None
    seen_cursors = set()
    observed_page_size = None
    total_elapsed = 0.0
    total_bytes = 0
    pages_fetched = 0
    snapshot_complete = True
    page_cap_hit = False
    duplicate_events = 0
    terminal_reason = "empty_page"

    for page in range(max_pages):
        if after is not None:
            if after in seen_cursors:
                snapshot_complete = False
                terminal_reason = "repeated_cursor"
                break
            seen_cursors.add(after)
        page_url = with_query(url, count=page_count, after=after)
        result = fetch(page_url)
        last = result
        pages_fetched += 1
        total_elapsed += result.elapsed_seconds
        total_bytes += result.response_size_bytes
        if not result.ok:
            if page == 0:
                result.terminal_reason = "http_error"
                return {"Success": False, "Value": []}, result
            snapshot_complete = False
            terminal_reason = "http_error"
            break

        body = result.json_body if isinstance(result.json_body, dict) else {}
        events = body.get("Value") or []
        if not isinstance(events, list) or not events:
            terminal_reason = "empty_page"
            break

        new_ids = []
        added = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("I")
            if event_id in seen:
                duplicate_events += 1
                continue
            seen.add(event_id)
            combined.append(event)
            added += 1
            if event_id is not None:
                new_ids.append(event_id)

        if first_cursor is None and new_ids:
            first_cursor = str(new_ids[0])
        if observed_page_size is None:
            observed_page_size = len(events)
        if added == 0:
            snapshot_complete = False
            terminal_reason = "zero_new_ids"
            break
        if len(events) < observed_page_size:
            # Verified VZip contract: a shorter page than the first
            # observed full page is the last page, not a requested-count miss.
            terminal_reason = "short_page"
            after = new_ids[-1] if new_ids else after
            break
        if not new_ids:
            snapshot_complete = False
            terminal_reason = "zero_new_ids"
            break
        after = new_ids[-1]
    else:
        page_cap_hit = True
        snapshot_complete = False
        terminal_reason = "runaway_guard"

    aggregated = FetchResult(
        url=url,
        ok=bool(combined) or (last is not None and last.ok),
        status_code=last.status_code if last is not None else None,
        content_type=last.content_type if last is not None else None,
        response_size_bytes=total_bytes,
        elapsed_seconds=total_elapsed,
        json_body={"Success": True, "Value": combined},
        error=None if combined or (last is not None and last.ok) else (last.error if last else None),
    )
    copy_cache_headers(aggregated, last)
    aggregated.pages_fetched = pages_fetched
    aggregated.page_cap_hit = page_cap_hit
    aggregated.snapshot_complete = snapshot_complete
    aggregated.unique_event_ids = len(seen)
    aggregated.duplicate_events = duplicate_events
    aggregated.terminal_reason = terminal_reason
    aggregated.first_cursor = first_cursor
    aggregated.last_cursor = None if after is None else str(after)
    return aggregated.json_body, aggregated


def _ordered_query(pairs) -> str:
    return urlencode([(key, value) for key, value in pairs if value is not None])


def build_champs_zip_url(vzip_url: str) -> str:
    parts = urlsplit(vzip_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sport = query.get("sports") or query.get("sport")
    pairs = [("sport", None if sport is None else str(sport))]
    pairs.extend((key, query.get(key)) for key in _CHAMP_LIST_KEYS)
    path = parts.path.replace("Get1x2_VZip", "GetChampsZip")
    return urlunsplit((parts.scheme, parts.netloc, path, _ordered_query(pairs), parts.fragment))


def build_champ_events_url(vzip_url: str, champ_id) -> str:
    parts = urlsplit(vzip_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    pairs = [("champs", str(champ_id)), ("count", str(CHAMP_EVENT_CAP))]
    pairs.extend((key, query.get(key)) for key in _CHAMP_EVENT_KEYS)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, _ordered_query(pairs), parts.fragment))


def _champ_rows(body):
    rows = (body or {}).get("Value") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("LI") is not None]


def fetch_vzip_by_champs(
    url: str,
    *,
    fetch=None,
    max_champs: int = MAX_PAGES,
    retries: int = 0,
    champ_concurrency: int = CHAMP_CONCURRENCY,
):
    """
    PREMATCH catalogue walk: championship list + per-champ VZip pages.

    Independent champ requests may run with bounded concurrency. A
    championship that returns the 50-event cap while advertising more
    games is incomplete -- `after=` is not available on these hosts.
    """
    if fetch is None:
        if retries:
            fetch = lambda page_url: fetch_json(page_url, retries=retries)  # noqa: E731
        else:
            fetch = fetch_json

    champs_url = build_champs_zip_url(url)
    champs_result = fetch(champs_url)
    if not champs_result.ok:
        envelope, window = fetch_vzip_all(url, fetch=fetch, max_pages=1)
        window.snapshot_complete = False
        window.terminal_reason = "champs_http_error"
        window.page_cap_hit = False
        return envelope, window

    champs = _champ_rows(champs_result.json_body)
    source_total = sum(int(row.get("GC") or 0) for row in champs)
    if not champs:
        empty = FetchResult(
            url=url,
            ok=True,
            status_code=champs_result.status_code,
            content_type=champs_result.content_type,
            response_size_bytes=champs_result.response_size_bytes,
            elapsed_seconds=champs_result.elapsed_seconds,
            json_body={"Success": True, "Value": []},
        )
        copy_cache_headers(empty, champs_result)
        empty.snapshot_complete = True
        empty.terminal_reason = "empty_page"
        empty.source_total = source_total
        empty.pages_fetched = 1
        return empty.json_body, empty

    limited = champs[:max_champs]
    page_cap_hit = len(champs) > max_champs
    combined = []
    seen = set()
    duplicate_events = 0
    pages_fetched = 1
    total_elapsed = champs_result.elapsed_seconds
    total_bytes = champs_result.response_size_bytes
    last = champs_result
    snapshot_complete = not page_cap_hit
    terminal_reason = "source_total"
    capped_champs = 0
    http_errors = 0

    def _one(row):
        champ_url = build_champ_events_url(url, row.get("LI"))
        return row, fetch(champ_url)

    workers = max(1, min(int(champ_concurrency or 1), len(limited)))
    if workers == 1:
        fetched_champs = [_one(row) for row in limited]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched_champs = list(pool.map(_one, limited))

    for row, result in fetched_champs:
        pages_fetched += 1
        total_elapsed += result.elapsed_seconds
        total_bytes += result.response_size_bytes
        last = result
        if not result.ok:
            snapshot_complete = False
            http_errors += 1
            continue
        events = ((result.json_body or {}).get("Value") if isinstance(result.json_body, dict) else None) or []
        if not isinstance(events, list):
            events = []
        advertised = int(row.get("GC") or 0)
        if len(events) >= CHAMP_EVENT_CAP and advertised > len(events):
            snapshot_complete = False
            capped_champs += 1
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("I")
            if event_id in seen:
                duplicate_events += 1
                continue
            seen.add(event_id)
            combined.append(event)

    if http_errors and not combined:
        terminal_reason = "http_error"
    elif http_errors:
        terminal_reason = "http_error"
    elif page_cap_hit:
        terminal_reason = "runaway_guard"
    elif capped_champs:
        terminal_reason = "page_size_cap"
    elif not combined:
        terminal_reason = "empty_page"
    else:
        terminal_reason = "source_total"

    aggregated = FetchResult(
        url=url,
        ok=bool(combined) or champs_result.ok,
        status_code=last.status_code if last is not None else champs_result.status_code,
        content_type=last.content_type if last is not None else champs_result.content_type,
        response_size_bytes=total_bytes,
        elapsed_seconds=total_elapsed,
        json_body={"Success": True, "Value": combined},
        error=None if combined or champs_result.ok else champs_result.error,
    )
    copy_cache_headers(aggregated, last)
    aggregated.pages_fetched = pages_fetched
    aggregated.page_cap_hit = page_cap_hit
    aggregated.snapshot_complete = snapshot_complete and not http_errors
    aggregated.unique_event_ids = len(seen)
    aggregated.duplicate_events = duplicate_events
    aggregated.source_total = source_total or None
    aggregated.terminal_reason = terminal_reason
    aggregated.first_cursor = None if not limited else str(limited[0].get("LI"))
    aggregated.last_cursor = None if not limited else str(limited[-1].get("LI"))
    return aggregated.json_body, aggregated
