"""
Persistent Betika workers (one for LIVE, one for PREMATCH).

Each is a single HTTP GET per 5s cycle -- no browser/session needed
(see kenyan/parsers/betika_parser.py for endpoint details).
"""
import time

from kenyan.config import BETIKA
from kenyan.http_utils import fetch_json
from kenyan.parsers.betika_parser import parse_matches
from kenyan.workers.base import BaseKenyanWorker, Diagnostics

LIVE_URL = (
    "https://live.betika.com/v1/uo/matches"
    "?page=1&limit=200&sub_type_id=1,186,340&sport=null&sort=1"
)
PREMATCH_URL = (
    "https://api.betika.com/v1/uo/matches"
    "?page=1&limit=200&sub_type_id=1,186,340&sport=1"
)


def _poll(url: str, status: str):
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

    raw_matches = (fetch_result.json_body or {}).get("data") or []

    try:
        matches = parse_matches(fetch_result.json_body, status=status)
        parser_error = None
    except Exception as exc:  # noqa: BLE001
        matches = []
        parser_error = f"{type(exc).__name__}: {exc}"

    football_events = sum(
        1
        for m in raw_matches
        if (m.get("sport_name") or "").strip().lower() == "soccer"
    )

    diagnostics = Diagnostics(
        endpoint_status="ok" if parser_error is None else "bad_payload",
        http_status_code=fetch_result.status_code,
        content_type=fetch_result.content_type,
        response_size_bytes=fetch_result.response_size_bytes,
        events_discovered=len(raw_matches),
        football_events=football_events,
        one_x_two_events=football_events,
        valid_normalized_events=len(matches),
        parser_error=parser_error,
        elapsed_seconds=fetch_result.elapsed_seconds,
        acquired_at=time.time(),
    )

    return matches, diagnostics


def build_live_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_live",
        poll_fn=lambda: _poll(LIVE_URL, "LIVE"),
    )


def build_prematch_worker() -> BaseKenyanWorker:
    return BaseKenyanWorker(
        name=f"{BETIKA}_prematch",
        poll_fn=lambda: _poll(PREMATCH_URL, "PREMATCH"),
    )
