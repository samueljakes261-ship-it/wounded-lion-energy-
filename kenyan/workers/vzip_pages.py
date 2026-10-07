"""
Walk 1xCorp Get1x2_VZip catalogues with the `after` cursor.

games1x2 `count=1000` and `skip=` return HTTP 400. Asking for
`count=400` still returns 50 events (verified live on 1xBet and 22Bet),
so a page is "full" at the observed size, not the requested count.
`after=<last event I>` continues until a short page.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kenyan.http_utils import FetchResult, fetch_json

PAGE_COUNT = 400
MAX_PAGES = 40


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
    fetch=fetch_json,
    page_count: int = PAGE_COUNT,
    max_pages: int = MAX_PAGES,
):
    combined = []
    seen = set()
    last = None
    after = None
    observed_page_size = None
    total_elapsed = 0.0
    total_bytes = 0

    for page in range(max_pages):
        page_url = with_query(url, count=page_count, after=after)
        result = fetch(page_url)
        last = result
        total_elapsed += result.elapsed_seconds
        total_bytes += result.response_size_bytes
        if not result.ok:
            if page == 0:
                return {"Success": False, "Value": []}, result
            break

        body = result.json_body if isinstance(result.json_body, dict) else {}
        events = body.get("Value") or []
        if not isinstance(events, list) or not events:
            break

        new_ids = []
        added = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("I")
            if event_id in seen:
                continue
            seen.add(event_id)
            combined.append(event)
            added += 1
            if event_id is not None:
                new_ids.append(event_id)

        if observed_page_size is None:
            observed_page_size = len(events)
        # Server may ignore count=400 and return 50. Stop only on a
        # short page, a repeated page, or a missing cursor.
        if added == 0 or len(events) < observed_page_size or not new_ids:
            break
        after = new_ids[-1]

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
    return aggregated.json_body, aggregated
