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

        markets = data["marketCatalogueList"]["content"]

        if not markets:
            break

        all_markets.extend(markets)

        page += 1

    return all_markets
