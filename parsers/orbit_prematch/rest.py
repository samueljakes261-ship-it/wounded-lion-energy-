"""Orbit prematch catalogue.

Live Orbit uses /customer/api/inplay/highlights (parsers/orbit/rest.py).
That file is frozen. Prematch uses the sport-page details endpoint that
the upcoming today/tomorrow/future tabs actually call:

POST /customer/api/sport/details?page=&size=
{id: 1, timeFilter: TODAY|TOMORROW|FUTURE, contextFilter: EVENT_TYPE, viewBy: TIME}
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import ORBIT_COOKIES, ORBIT_CSRF_TOKEN

BASE_URL = "https://www.orbitxch.com"
SOCCER_EVENT_TYPE = 1
TABS = ("TODAY", "TOMORROW", "FUTURE")
MAX_PAGES = 30
REQUEST_TIMEOUT = 30
PAGE_SIZE = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.orbitxch.com",
    "Referer": "https://www.orbitxch.com/customer/sport/1?tab=upcoming&mobNavContentTab=today",
    "Content-Type": "application/json",
    "x-csrf-token": ORBIT_CSRF_TOKEN,
    "Cookie": ORBIT_COOKIES,
}


def _extract_markets(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    catalogue = data.get("marketCatalogueList") or data.get("markets") or {}
    if isinstance(catalogue, dict):
        content = catalogue.get("content") or catalogue.get("markets") or []
        if isinstance(content, list):
            return content
    for key in ("content", "marketCatalogues", "marketCatalogue", "attachments"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            inner = value.get("content") or value.get("markets")
            if isinstance(inner, list):
                return inner
    return []


def _is_prematch_market(market):
    if not isinstance(market, dict):
        return False
    description = market.get("description") or {}
    event = market.get("event") or {}
    if market.get("inPlay") is True or event.get("inPlay") is True:
        return False
    status = str(
        market.get("status")
        or description.get("status")
        or event.get("status")
        or ""
    ).upper()
    if status in ("CLOSED", "SUSPENDED", "INACTIVE"):
        return False
    return True


def _is_match_odds(market):
    name = (
        market.get("marketName")
        or (market.get("description") or {}).get("marketName")
        or ""
    ).lower()
    if "match odds" in name or "match winner" in name:
        return True
    return False


def _filter_markets(raw_markets, stats=None):
    kept = []
    stats = stats if stats is not None else {}
    for market in raw_markets:
        if not _is_prematch_market(market):
            stats["rejected_inplay_or_closed"] = stats.get("rejected_inplay_or_closed", 0) + 1
            continue
        if not _is_match_odds(market):
            stats["rejected_not_match_odds"] = stats.get("rejected_not_match_odds", 0) + 1
            continue
        if not market.get("marketId"):
            stats["rejected_missing_market_id"] = stats.get("rejected_missing_market_id", 0) + 1
            continue
        if not (market.get("event") or {}).get("id"):
            stats["rejected_missing_event_id"] = stats.get("rejected_missing_event_id", 0) + 1
            continue
        if not market.get("runners"):
            stats["rejected_missing_runners"] = stats.get("rejected_missing_runners", 0) + 1
            continue
        kept.append(market)
    return kept


def _post_page(tab, page):
    payload = {
        "id": SOCCER_EVENT_TYPE,
        "timeFilter": tab,
        "contextFilter": "EVENT_TYPE",
        "viewBy": "TIME",
    }
    url = (
        f"{BASE_URL}/customer/api/sport/details"
        f"?page={page}&size={PAGE_SIZE}"
    )
    last_error = None
    for attempt in range(3):
        try:
            response = requests.post(
                url, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            if response.status_code >= 400:
                body = response.text[:180].replace("\n", " ")
                raise RuntimeError(f"HTTP {response.status_code} {body}")
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                continue
    raise last_error


def _summarize_page(tab, page, data):
    markets = _extract_markets(data)
    catalogue = data.get("marketCatalogueList") or {}
    last_flag = catalogue.get("last")
    total_pages = catalogue.get("totalPages") or 1
    total_elements = catalogue.get("totalElements")
    if page == 0 or last_flag is True:
        print(
            f"[PREMATCH][ORBIT] {tab} pagination "
            f"page={page} size={PAGE_SIZE} batch={len(markets)} "
            f"last={last_flag} totalPages={total_pages} "
            f"totalElements={total_elements}"
        )
    return markets, last_flag, total_pages


def _fetch_pages(tab, pages):
    if not pages:
        return [], 0
    collected = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_post_page, tab, page) for page in pages]
        for future in as_completed(futures):
            collected.extend(_extract_markets(future.result()))
    return collected, len(pages)


def _fetch_tab_first_page(tab):
    data = _post_page(tab, 0)
    markets, last_flag, total_pages = _summarize_page(tab, 0, data)
    stats = {"rejected_inplay_or_closed": 0}
    kept = _filter_markets(markets, stats)
    remaining = []
    if last_flag is not True and markets:
        if isinstance(total_pages, int) and total_pages > 1:
            remaining = list(range(1, min(total_pages, MAX_PAGES)))
        elif len(markets) >= PAGE_SIZE:
            remaining = list(range(1, MAX_PAGES))
    return kept, {
        "tab": tab,
        "pages": 1,
        "raw": len(markets),
        "kept": len(kept),
        "rejected": stats,
        "remaining_pages": remaining,
    }


def _fetch_tab_remaining(tab, remaining_pages):
    if not remaining_pages:
        return [], {
            "tab": tab,
            "pages": 0,
            "raw": 0,
            "kept": 0,
            "rejected": {},
        }
    collected, pages_fetched = _fetch_pages(tab, remaining_pages)
    stats = {"rejected_inplay_or_closed": 0}
    kept = _filter_markets(collected, stats)
    print(
        f"[PREMATCH][ORBIT] {tab} remaining pages={pages_fetched} "
        f"raw={len(collected)} match_odds={len(kept)} "
        f"rejected={stats}"
    )
    return kept, {
        "tab": tab,
        "pages": pages_fetched,
        "raw": len(collected),
        "kept": len(kept),
        "rejected": stats,
    }


def _fetch_tab(tab):
    first, first_stats = _fetch_tab_first_page(tab)
    rest, rest_stats = _fetch_tab_remaining(tab, first_stats["remaining_pages"])
    kept = first + rest
    pages_fetched = first_stats["pages"] + rest_stats["pages"]
    raw_count = first_stats["raw"] + rest_stats["raw"]
    stats = dict(first_stats["rejected"])
    for key, value in rest_stats["rejected"].items():
        stats[key] = stats.get(key, 0) + value
    print(
        f"[PREMATCH][ORBIT] {tab} pages={pages_fetched} "
        f"raw={raw_count} match_odds={len(kept)} "
        f"rejected={stats}"
    )
    return kept, {
        "tab": tab,
        "pages": pages_fetched,
        "raw": raw_count,
        "kept": len(kept),
        "rejected": stats,
    }


def get_upcoming_markets():
    """Soccer Match Odds markets for today + tomorrow + future tabs."""
    collected = {}
    tab_stats = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_tab, tab): tab for tab in TABS}
        for future in as_completed(futures):
            tab = futures[future]
            try:
                markets, stats = future.result()
            except Exception as exc:
                print(
                    f"[ORBIT PREMATCH] {tab.lower()} catalogue failed "
                    f"({type(exc).__name__}: {exc})"
                )
                continue
            tab_stats.append(stats)
            added = 0
            for market in markets:
                market_id = market.get("marketId")
                if not market_id or market_id in collected:
                    continue
                collected[market_id] = market
                added += 1
            print(
                f"[ORBIT PREMATCH] {tab.lower()} unique +{added} "
                f"(merged total {len(collected)})"
            )
    tab_stats.sort(key=lambda row: TABS.index(row["tab"]) if row["tab"] in TABS else 99)
    if not collected:
        raise RuntimeError("Orbit prematch catalogue empty")
    print(
        "[PREMATCH][ORBIT] REST "
        + " ".join(
            f"{row['tab']}: raw={row['raw']} kept={row['kept']}"
            for row in tab_stats
        )
        + f" unique_markets={len(collected)}"
    )
    print(f"[ORBIT PREMATCH] events parsed: {len(collected)} catalogue markets")
    return list(collected.values())
