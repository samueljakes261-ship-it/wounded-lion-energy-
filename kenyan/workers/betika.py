"""
Persistent Betika workers (one for LIVE, one for PREMATCH).

Each cycle GETs the existing football window plus extra sports pages.
Pagination is required: limit=10 is a subset (tennis meta.total ~79).
"""
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kenyan.config import BETIKA
from kenyan.http_utils import fetch_json
from kenyan.parsers.betika_parser import parse_all_matches
from kenyan.workers.base import BaseKenyanWorker, Diagnostics

LIVE_URL = (
    "https://live.betika.com/v1/uo/matches"
    "?page=1&limit=200&sub_type_id=1,186,340&sport=null&sort=1"
)
PREMATCH_URL = (
    "https://api.betika.com/v1/uo/matches"
    "?page=1&limit=200&sub_type_id=1,186,340&sport=1"
)
PREMATCH_SPORT_URLS = (
    "https://api.betika.com/v1/uo/matches?page=1&limit=100&tab=&sub_type_id=1,186,340&sport_id=28&sort_id=1&period_id=-1&esports=false",
    "https://api.betika.com/v1/uo/matches?page=1&limit=100&tab=&sub_type_id=1,186,340&sport_id=30&sort_id=1&period_id=-1&esports=false",
    "https://api.betika.com/v1/uo/matches?page=1&limit=100&tab=&sub_type_id=1,186,340&sport_id=35&sort_id=1&period_id=-1&esports=false",
)
MAX_PAGES = 8


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page)
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
        if len(rows) < int(query_limit(url)):
            break
    payload = {"data": combined, "meta": {"total": total}}
    return payload, last


def query_limit(url: str) -> int:
    query = dict(parse_qsl(urlsplit(url).query))
    try:
        return max(int(query.get("limit") or 100), 1)
    except (TypeError, ValueError):
        return 100


def _poll(urls, status: str):
    combined_rows = []
    seen_ids = set()
    last = None
    parser_error = None
    elapsed = 0.0
    bytes_total = 0
    status_code = None
    content_type = None
    for url in urls:
        payload, fetch_result = _fetch_pages(url)
        last = fetch_result
        if fetch_result is not None:
            elapsed += fetch_result.elapsed_seconds
            bytes_total += fetch_result.response_size_bytes
            status_code = fetch_result.status_code
            content_type = fetch_result.content_type
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
    ok = last is not None and last.ok and parser_error is None
    diagnostics = Diagnostics(
        endpoint_status="ok" if ok else (
            "http_error" if last is not None and last.status_code else "exception"
        ) if parser_error is None else "bad_payload",
        http_status_code=status_code if last is None or last.ok else last.status_code,
        content_type=content_type,
        response_size_bytes=bytes_total,
        events_discovered=len(combined_rows),
        football_events=football_events,
        one_x_two_events=football_events,
        valid_normalized_events=len(matches),
        parser_error=parser_error or (last.error if last is not None and not last.ok else None),
        elapsed_seconds=elapsed,
        acquired_at=time.time(),
    )
    return matches, diagnostics


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_live",
        poll_fn=lambda: _poll((LIVE_URL,), "LIVE"),
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_prematch",
        poll_fn=lambda: _poll((PREMATCH_URL,) + PREMATCH_SPORT_URLS, "PREMATCH"),
    )
