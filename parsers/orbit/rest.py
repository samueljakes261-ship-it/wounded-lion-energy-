import requests
from requests import HTTPError

from config import ORBIT_COOKIES, ORBIT_CSRF_TOKEN
from parsers.orbit.access import OrbitAccessError, classify_http_status
from parsers.orbit.proxy import requests_proxies

BASE_URL = "https://www.orbitxch.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.orbitxch.com",
    "Referer": "https://www.orbitxch.com/customer/inplay/highlights",
    "Content-Type": "application/json",
    "x-csrf-token": ORBIT_CSRF_TOKEN,
    "Cookie": ORBIT_COOKIES,
}


def _download_page(page, sports):

    url = (
        BASE_URL
        + f"/customer/api/inplay/highlights?page={page}&size=100"
    )

    payload = {
        "eventTypeIds": sports
    }

    try:
        post_kwargs = {
            "json": payload,
            "headers": HEADERS,
            "timeout": 20,
        }
        proxies = requests_proxies()
        if proxies is not None:
            post_kwargs["proxies"] = proxies
        response = requests.post(url, **post_kwargs)
    except requests.RequestException as exc:
        raise OrbitAccessError(
            "network",
            None,
            type(exc).__name__,
        ) from exc

    try:
        response.raise_for_status()
    except HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        raise OrbitAccessError(
            classify_http_status(status or 0),
            status,
            "rest_highlights",
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise OrbitAccessError(
            "non_json_body",
            response.status_code,
            "rest_highlights",
        ) from exc


def catalogue_markets(data) -> list:
    """Rows from the in-play highlights body.

    The old body is marketCatalogueList.content. A later body uses the
    same wrappers as the prematch sport page. An unrecognised page is
    empty instead of raising, so one odd response does not drop the session.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    catalogue = data.get("marketCatalogueList")
    if isinstance(catalogue, list):
        return [row for row in catalogue if isinstance(row, dict)]
    if isinstance(catalogue, dict):
        content = catalogue.get("content") or catalogue.get("markets") or []
        if isinstance(content, list):
            return [row for row in content if isinstance(row, dict)]
    for key in ("content", "marketCatalogues", "marketCatalogue", "markets"):
        value = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            inner = value.get("content") or value.get("markets")
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
    return []


def get_all_live_markets():

    sports = [
        1,   # Soccer
        2,   # Tennis
        3,   # Golf
        4,   # Cricket
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
    ]

    all_markets = []

    page = 0

    while True:

        data = _download_page(page, sports)

        markets = catalogue_markets(data)

        if not markets:
            break

        all_markets.extend(markets)
        catalogue = data.get("marketCatalogueList") if isinstance(data, dict) else None
        last_page = False
        if isinstance(catalogue, dict) and catalogue.get("last") is True:
            last_page = True
        if isinstance(data, dict) and data.get("last") is True:
            last_page = True
        page += 1
        if last_page or page > 40:
            break

    return all_markets
