"""
Persistent Betika workers (one for LIVE, one for PREMATCH).

sub_type_id 18 is TOTAL (Over/Under lines such as OVER 2.5 / UNDER 2.5).
219 is basketball WINNER (INCL. OVERTIME), the two-way moneyline that
matches 1xBet/22Bet group 101. 1,186,340 remain other winner markets.
Pages are walked until meta.total.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kenyan.config import (
    BETIKA,
    KENYAN_BETIKA_MAX_PAGES,
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_LIVE_STALE_AFTER_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_RUNAWAY_PAGES,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    LIVE,
)
from kenyan.http_utils import copy_cache_headers, fetch_json
from kenyan.parsers.betika_parser import parse_all_matches
from kenyan.workers.base import BaseKenyanWorker, Diagnostics, apply_catalogue_status

BETIKA_SUB_TYPES = "1,18,186,219,340"
MAX_PAGES = KENYAN_BETIKA_MAX_PAGES
PAGE_LIMIT = 200

LIVE_URL = (
    "https://live.betika.com/v1/uo/matches"
    f"?page=1&limit={PAGE_LIMIT}&sub_type_id={BETIKA_SUB_TYPES}&sport=null&sort=1"
)
PREMATCH_URLS = (
    f"https://api.betika.com/v1/uo/matches?page=1&limit={PAGE_LIMIT}&sub_type_id={BETIKA_SUB_TYPES}&sport=1",
    f"https://api.betika.com/v1/uo/matches?page=1&limit={PAGE_LIMIT}&tab=&sub_type_id={BETIKA_SUB_TYPES}&sport_id=28&sort_id=1&period_id=-1&esports=false",
    f"https://api.betika.com/v1/uo/matches?page=1&limit={PAGE_LIMIT}&tab=&sub_type_id={BETIKA_SUB_TYPES}&sport_id=30&sort_id=1&period_id=-1&esports=false",
    f"https://api.betika.com/v1/uo/matches?page=1&limit={PAGE_LIMIT}&tab=&sub_type_id={BETIKA_SUB_TYPES}&sport_id=35&sort_id=1&period_id=-1&esports=false",
)


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page)
    query["limit"] = str(PAGE_LIMIT)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _fetch_pages(
    url: str,
    *,
    max_pages: int = MAX_PAGES,
    retries: int = 0,
    honor_requested_short_page: bool = True,
):
    combined = []
    seen_ids = set()
    last = None
    total = None
    pages_fetched = 0
    snapshot_complete = True
    page_cap_hit = False
    duplicate_events = 0
    terminal_reason = "empty_page"
    observed_page_size = None
    first_cursor = None
    page = 1
    while page <= max_pages:
        page_url = _with_page(url, page)
        fetch_result = (
            fetch_json(page_url, retries=retries) if retries else fetch_json(page_url)
        )
        last = fetch_result
        pages_fetched += 1
        if not fetch_result.ok:
            snapshot_complete = False
            terminal_reason = "http_error"
            break
        body = fetch_result.json_body if isinstance(fetch_result.json_body, dict) else {}
        rows = body.get("data") or []
        meta = body.get("meta") or {}
        try:
            reported = int(meta.get("total") or 0)
            if reported:
                total = reported
        except (TypeError, ValueError):
            pass
        if not isinstance(rows, list) or not rows:
            if total and len(combined) < total:
                snapshot_complete = False
                terminal_reason = "empty_before_source_total"
            else:
                terminal_reason = "empty_page"
            break
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_id = row.get("match_id") or row.get("game_id") or id(row)
            if event_id in seen_ids:
                duplicate_events += 1
                continue
            seen_ids.add(event_id)
            combined.append(row)
            added += 1
        if first_cursor is None:
            first_cursor = str(page)
        if observed_page_size is None:
            observed_page_size = len(rows)
        if total and len(combined) >= total:
            terminal_reason = "source_total"
            break
        if added == 0:
            snapshot_complete = False
            terminal_reason = "zero_new_ids"
            break
        if honor_requested_short_page:
            if len(rows) < PAGE_LIMIT:
                terminal_reason = "short_page"
                break
        elif total:
            # meta.total is authoritative: a page shorter than the
            # requested limit is not the catalogue end if more remain.
            pass
        elif len(rows) < observed_page_size:
            terminal_reason = "short_page"
            break
        page += 1
    else:
        page_cap_hit = True
        snapshot_complete = False
        terminal_reason = "runaway_guard"
    if (
        not honor_requested_short_page
        and total
        and len(seen_ids) < total
    ):
        snapshot_complete = False
        if terminal_reason not in (
            "http_error",
            "runaway_guard",
            "zero_new_ids",
            "empty_before_source_total",
        ):
            terminal_reason = "empty_before_source_total"
    if last is not None:
        last.pages_fetched = pages_fetched
        last.page_cap_hit = page_cap_hit
        last.snapshot_complete = snapshot_complete
        last.source_total = total
        last.unique_event_ids = len(seen_ids)
        last.duplicate_events = duplicate_events
        last.terminal_reason = terminal_reason
        last.first_cursor = first_cursor
        last.last_cursor = str(page)
    payload = {"data": combined, "meta": {"total": total}}
    return payload, last


def _poll(urls, status: str):
    combined_rows = []
    seen_ids = set()
    last = None
    last_ok = None
    parser_error = None
    elapsed = 0.0
    bytes_total = 0
    status_code = None
    content_type = None
    any_ok = False
    urls = tuple(urls)
    max_pages = KENYAN_BETIKA_MAX_PAGES if status == LIVE else KENYAN_PREMATCH_RUNAWAY_PAGES
    retries = 0 if status == LIVE else 2
    honor_requested_short_page = status == LIVE
    fetch_kwargs = dict(
        max_pages=max_pages,
        retries=retries,
        honor_requested_short_page=honor_requested_short_page,
    )
    if len(urls) <= 1:
        fetched = [_fetch_pages(urls[0], **fetch_kwargs)] if urls else []
    else:
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            fetched = list(
                pool.map(lambda url, kwargs=fetch_kwargs: _fetch_pages(url, **kwargs), urls)
            )
    for payload, fetch_result in fetched:
        last = fetch_result
        if fetch_result is not None:
            elapsed += fetch_result.elapsed_seconds
            bytes_total += fetch_result.response_size_bytes
            status_code = fetch_result.status_code
            content_type = fetch_result.content_type
            if fetch_result.ok:
                any_ok = True
                last_ok = fetch_result
            if not fetch_result.ok and not payload.get("data"):
                continue
        for row in payload.get("data") or []:
            event_id = row.get("match_id") or row.get("game_id") or id(row)
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            combined_rows.append(row)

    body = {"data": combined_rows}
    try:
        matches = parse_all_matches(body, status=status)
    except Exception as exc:  # noqa: BLE001
        matches = []
        parser_error = f"{type(exc).__name__}: {exc}"

    football_events = sum(
        1
        for m in combined_rows
        if (m.get("sport_name") or "").strip().lower() == "soccer"
    )
    ok = any_ok and parser_error is None
    failed = last_ok is None and last is not None
    pages_fetched = sum(getattr(result, "pages_fetched", 0) or 0 for _payload, result in fetched if result)
    page_cap_hit = any(getattr(result, "page_cap_hit", False) for _payload, result in fetched if result)
    snapshot_complete = all(
        getattr(result, "snapshot_complete", True) for _payload, result in fetched if result
    ) if fetched else True
    source_totals = [
        getattr(result, "source_total", None) for _payload, result in fetched if result
    ]
    source_total = sum(value for value in source_totals if value)
    unique_event_ids = len(seen_ids)
    duplicate_events = sum(
        getattr(result, "duplicate_events", 0) or 0 for _payload, result in fetched if result
    )
    incomplete_reasons = [
        getattr(result, "terminal_reason", None)
        for _payload, result in fetched
        if result and not getattr(result, "snapshot_complete", True)
    ]
    complete_reasons = [
        getattr(result, "terminal_reason", None)
        for _payload, result in fetched
        if result and getattr(result, "snapshot_complete", True)
    ]
    if page_cap_hit:
        terminal_reason = "runaway_guard"
    elif incomplete_reasons:
        terminal_reason = next((reason for reason in incomplete_reasons if reason), "incomplete")
    else:
        terminal_reason = next((reason for reason in complete_reasons if reason), None)
    first_cursors = [
        getattr(result, "first_cursor", None)
        for _payload, result in fetched
        if result and getattr(result, "first_cursor", None)
    ]
    last_cursors = [
        getattr(result, "last_cursor", None)
        for _payload, result in fetched
        if result and getattr(result, "last_cursor", None)
    ]
    diagnostics = Diagnostics(
        endpoint_status="ok" if ok else (
            "http_error" if last is not None and last.status_code else "exception"
        ) if parser_error is None else "bad_payload",
        http_status_code=(
            last_ok.status_code if last_ok is not None else (
                status_code if last is None or last.ok else last.status_code
            )
        ),
        content_type=content_type if last_ok is None else last_ok.content_type,
        response_size_bytes=bytes_total,
        events_discovered=len(combined_rows),
        football_events=football_events,
        one_x_two_events=football_events,
        valid_normalized_events=len(matches),
        parser_error=parser_error or (
            None if any_ok else (last.error if failed and not last.ok else None)
        ),
        elapsed_seconds=elapsed,
        acquired_at=time.time(),
        pages_fetched=pages_fetched,
        page_cap_hit=page_cap_hit,
        snapshot_complete=snapshot_complete,
        source_total=source_total or None,
        unique_event_ids=unique_event_ids,
        duplicate_events=duplicate_events,
        terminal_reason=terminal_reason,
        first_cursor=first_cursors[0] if first_cursors else None,
        last_cursor=last_cursors[-1] if last_cursors else None,
    )
    copy_cache_headers(diagnostics, last_ok or last)
    return matches, apply_catalogue_status(diagnostics)


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_live",
        poll_fn=lambda: _poll((LIVE_URL,), "LIVE"),
        poll_interval_seconds=KENYAN_LIVE_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_LIVE_STALE_AFTER_SECONDS,
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_prematch",
        poll_fn=lambda: _poll(PREMATCH_URLS, "PREMATCH"),
        poll_interval_seconds=KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
        retention_seconds=KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    )
