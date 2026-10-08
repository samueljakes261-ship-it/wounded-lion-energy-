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
    KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
)
from kenyan.http_utils import fetch_json
from kenyan.parsers.betika_parser import parse_all_matches
from kenyan.workers.base import BaseKenyanWorker, Diagnostics

BETIKA_SUB_TYPES = "1,18,186,219,340"
MAX_PAGES = 40
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


def _fetch_pages(url: str):
    combined = []
    seen_ids = set()
    last = None
    total = None
    for page in range(1, MAX_PAGES + 1):
        fetch_result = fetch_json(_with_page(url, page))
        last = fetch_result
        if not fetch_result.ok:
            break
        body = fetch_result.json_body if isinstance(fetch_result.json_body, dict) else {}
        rows = body.get("data") or []
        meta = body.get("meta") or {}
        try:
            total = int(meta.get("total") or 0)
        except (TypeError, ValueError):
            total = total or 0
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_id = row.get("match_id") or row.get("game_id") or id(row)
            if event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            combined.append(row)
        if total and len(combined) >= total:
            break
        if len(rows) < PAGE_LIMIT:
            break
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
    if len(urls) <= 1:
        fetched = [_fetch_pages(urls[0])] if urls else []
    else:
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            fetched = list(pool.map(_fetch_pages, urls))
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
    )
    return matches, diagnostics


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_live",
        poll_fn=lambda: _poll((LIVE_URL,), "LIVE"),
        poll_interval_seconds=KENYAN_LIVE_POLL_INTERVAL_SECONDS,
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_prematch",
        poll_fn=lambda: _poll(PREMATCH_URLS, "PREMATCH"),
        poll_interval_seconds=KENYAN_PREMATCH_POLL_INTERVAL_SECONDS,
    )
