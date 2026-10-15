"""Combine multi-URL Kenyan polls without letting one failed extra sport blank the cycle."""

import time
from concurrent.futures import ThreadPoolExecutor

from kenyan.config import LIVE
from kenyan.workers.base import Diagnostics, apply_catalogue_status

# More specific acquisition failures outrank remainder-window status so
# a later HTTP error cannot hide a 50-event championship cap, and a
# runaway guard cannot be reported as a clean source total.
_TERMINAL_REASON_RANK = {
    "runaway_guard": 0,
    "champs_http_error": 1,
    "http_error": 2,
    "parse_error": 3,
    "page_size_cap": 4,
    "source_total_shortfall": 5,
    "empty_before_source_total": 6,
    "repeated_cursor": 7,
    "zero_new_ids": 8,
}


def combine_match_polls(results):
    combined = []
    seen = set()
    ok_diagnostics = None
    fail_diagnostics = None
    discovered = 0
    football = 0
    elapsed = 0.0
    bytes_total = 0
    pages_fetched = 0
    page_cap_hit = False
    snapshot_complete = True
    unique_event_ids = 0
    duplicate_events = 0
    source_total = 0
    incomplete_reasons = []
    complete_reasons = []
    first_cursor = None
    last_cursor = None
    capped_partitions = 0

    for matches, diagnostics in results:
        discovered += diagnostics.events_discovered
        football += diagnostics.football_events
        elapsed += diagnostics.elapsed_seconds
        bytes_total += diagnostics.response_size_bytes
        pages_fetched += getattr(diagnostics, "pages_fetched", 0) or 0
        unique_event_ids += getattr(diagnostics, "unique_event_ids", 0) or 0
        duplicate_events += getattr(diagnostics, "duplicate_events", 0) or 0
        source_total += getattr(diagnostics, "source_total", 0) or 0
        page_cap_hit = page_cap_hit or bool(getattr(diagnostics, "page_cap_hit", False))
        snapshot_complete = snapshot_complete and bool(
            getattr(diagnostics, "snapshot_complete", True)
        )
        reason = getattr(diagnostics, "terminal_reason", None)
        if getattr(diagnostics, "snapshot_complete", True):
            if reason:
                complete_reasons.append(reason)
        elif reason:
            incomplete_reasons.append(reason)
        if first_cursor is None and getattr(diagnostics, "first_cursor", None):
            first_cursor = diagnostics.first_cursor
        if getattr(diagnostics, "last_cursor", None):
            last_cursor = diagnostics.last_cursor
        capped_partitions += getattr(diagnostics, "capped_partitions", 0) or 0
        if diagnostics.endpoint_status == "ok" and diagnostics.parser_error is None:
            ok_diagnostics = diagnostics
        else:
            fail_diagnostics = diagnostics
        for match in matches:
            key = (
                match.bookmaker,
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

    chosen = ok_diagnostics or fail_diagnostics or Diagnostics(endpoint_status="exception")
    chosen.valid_normalized_events = len(combined)
    chosen.events_discovered = max(chosen.events_discovered, discovered, len(combined))
    chosen.football_events = max(chosen.football_events, football)
    chosen.elapsed_seconds = elapsed
    chosen.response_size_bytes = bytes_total
    chosen.pages_fetched = pages_fetched
    chosen.page_cap_hit = page_cap_hit
    chosen.snapshot_complete = snapshot_complete
    chosen.unique_event_ids = unique_event_ids
    chosen.duplicate_events = duplicate_events
    chosen.source_total = source_total or None
    if page_cap_hit:
        chosen.terminal_reason = "runaway_guard"
    elif incomplete_reasons:
        chosen.terminal_reason = min(
            incomplete_reasons,
            key=lambda reason: _TERMINAL_REASON_RANK.get(reason, 50),
        )
    elif complete_reasons:
        chosen.terminal_reason = complete_reasons[0]
    chosen.first_cursor = first_cursor
    chosen.last_cursor = last_cursor
    chosen.capped_partitions = capped_partitions
    if combined and ok_diagnostics is not None:
        chosen.endpoint_status = "ok"
        chosen.parser_error = None
    apply_catalogue_status(chosen)
    return combined, chosen


def map_polls(poll_one, urls, status: str):
    """Run each catalogue URL concurrently, then combine like sequential polls."""
    urls = tuple(urls)
    started = time.monotonic()
    if not urls:
        return combine_match_polls([])
    concurrent = (status or "").upper() == LIVE and len(urls) > 1
    if not concurrent:
        results = [poll_one(url, status) for url in urls]
    else:
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            results = list(pool.map(lambda url: poll_one(url, status), urls))
    combined, diagnostics = combine_match_polls(results)
    # Wall-clock of the concurrent fan-out, not the sum of each URL.
    diagnostics.elapsed_seconds = time.monotonic() - started
    return combined, diagnostics
