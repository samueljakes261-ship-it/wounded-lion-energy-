import requests

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

    "x-csrf-token": "a95b617c-c16d-4297-885d-476f7061fccb",

    "Cookie": (
        "BIAB_LANGUAGE=en; "
        "COLLAPSE_SIDEBAR=false; "
        "BIAB_TZ=-180; "
        "COLLAPSE-LEFT_PANEL_COLLAPSE_GROUP-SPORT_COLLAPSE=true; "
        "BIAB_AN=ead97c02-9101-47f3-99cf-e1deb0b5c955; "
        "CSRF-TOKEN=a95b617c-c16d-4297-885d-476f7061fccb; "
        "AWSALB=HdmCBwOUUaHiryv2FwtUtmeoZyCcUU//29ixkbam8bxfDJcxspQJUidEchidJtC6nYAyeXIGSCfPUHG9HHD3MGA8Xo+1Y2wDcjPu0MtrkXOkCrSzT1ZGZQdFiQ0F; "
        "AWSALBCORS=HdmCBwOUUaHiryv2FwtUtmeoZyCcUU//29ixkbam8bxfDJcxspQJUidEchidJtC6nYAyeXIGSCfPUHG9HHD3MGA8Xo+1Y2wDcjPu0MtrkXOkCrSzT1ZGZQdFiQ0F"
    ),
}


def _download_page(page, sports):

    url = (
        BASE_URL
        + f"/customer/api/inplay/highlights?page={page}&size=100"
    )

    payload = {
        "eventTypeIds": sports
    }

    response = requests.post(
        url,
        json=payload,
        headers=HEADERS,
        timeout=20,
    )

    response.raise_for_status()

    return response.json()


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

        print(f"Downloading page {page}...")

        data = _download_page(page, sports)

        markets = data["marketCatalogueList"]["content"]

        if not markets:
            break

        all_markets.extend(markets)

        page += 1

    print(f"\nDownloaded {len(all_markets)} markets.\n")

    return all_markets