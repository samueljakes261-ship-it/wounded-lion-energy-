"""Orbit prematch catalogue.

Live Orbit uses /customer/api/inplay/highlights (parsers/orbit/rest.py).
That file is frozen. Prematch uses the sport-page details endpoint that
the upcoming today/tomorrow/future tabs actually call:

POST /customer/api/sport/details?page=&size=
{id: 1, timeFilter: TODAY|TOMORROW|FUTURE, contextFilter: EVENT_TYPE, viewBy: TIME}
"""

import requests

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
    if not name:
        return True
    if "match odds" in name or "match winner" in name:
        return True
    skip = ("over", "under", "handicap", "corner", "both teams", "correct score")
    return not any(token in name for token in skip)


def _filter_markets(raw_markets):
    kept = []
    for market in raw_markets:
        if not _is_prematch_market(market):
            continue
        if not _is_match_odds(market):
            continue
        if not market.get("marketId"):
            continue
        if not (market.get("event") or {}).get("id"):
            continue
        if not market.get("runners"):
            continue
        kept.append(market)
    return kept


def _fetch_tab(tab):
    payload = {
        "id": SOCCER_EVENT_TYPE,
        "timeFilter": tab,
        "contextFilter": "EVENT_TYPE",
        "viewBy": "TIME",
    }
    collected = []
    for page in range(MAX_PAGES):
        url = (
            f"{BASE_URL}/customer/api/sport/details"
            f"?page={page}&size={PAGE_SIZE}"
        )
        data = None
        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(
                    url, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT
                )
                if response.status_code >= 400:
                    body = response.text[:180].replace("\n", " ")
                    raise RuntimeError(
                        f"HTTP {response.status_code} {body}"
                    )
                data = response.json()
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    continue
        if last_error is not None:
            raise last_error
        markets = _extract_markets(data)
        if not markets:
            break
        collected.extend(markets)
        catalogue = data.get("marketCatalogueList") or {}
        if catalogue.get("last") is True:
            break
        if len(markets) < PAGE_SIZE:
            break
    return _filter_markets(collected)


def get_upcoming_markets():
    """Soccer Match Odds markets for today + tomorrow + future tabs."""
    collected = {}
    for tab in TABS:
        try:
            markets = _fetch_tab(tab)
            added = 0
            for market in markets:
                market_id = market.get("marketId")
                if not market_id or market_id in collected:
                    continue
                collected[market_id] = market
                added += 1
            print(f"[ORBIT PREMATCH] {tab.lower()} page: +{added} (total {len(collected)})")
        except Exception as exc:
            print(
                f"[ORBIT PREMATCH] {tab.lower()} catalogue failed "
                f"({type(exc).__name__}: {exc})"
            )
    if not collected:
        raise RuntimeError("Orbit prematch catalogue empty")
    print(f"[ORBIT PREMATCH] events parsed: {len(collected)} catalogue markets")
    return list(collected.values())
