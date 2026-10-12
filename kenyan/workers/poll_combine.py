"""Combine multi-URL Kenyan polls without letting one failed extra sport blank the cycle."""

import time
from concurrent.futures import ThreadPoolExecutor

from kenyan.workers.base import Diagnostics


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

    for matches, diagnostics in results:
        discovered += diagnostics.events_discovered
        football += diagnostics.football_events
        elapsed += diagnostics.elapsed_seconds
        bytes_total += diagnostics.response_size_bytes
        pages_fetched += getattr(diagnostics, "pages_fetched", 0) or 0
        page_cap_hit = page_cap_hit or bool(getattr(diagnostics, "page_cap_hit", False))
        snapshot_complete = snapshot_complete and bool(
            getattr(diagnostics, "snapshot_complete", True)
        )
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
    if combined and ok_diagnostics is not None:
        chosen.endpoint_status = "ok"
        chosen.parser_error = None
    return combined, chosen


def map_polls(poll_one, urls, status: str):
    """Run each catalogue URL concurrently, then combine like sequential polls."""
    urls = tuple(urls)
    started = time.monotonic()
    if not urls:
        return combine_match_polls([])
    if len(urls) == 1:
        combined, diagnostics = combine_match_polls([poll_one(urls[0], status)])
        diagnostics.elapsed_seconds = time.monotonic() - started
        return combined, diagnostics
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        results = list(pool.map(lambda url: poll_one(url, status), urls))
    combined, diagnostics = combine_match_polls(results)
    # Wall-clock of the concurrent fan-out, not the sum of each URL.
    diagnostics.elapsed_seconds = time.monotonic() - started
    return combined, diagnostics
