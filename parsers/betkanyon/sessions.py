import requests

BASE_URL = "https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"

session = requests.Session()


def get_tournament_feed(
    tournament_id,
    cookies,
    headers,
):
    """
    Downloads the encrypted response for ONE tournament.
    Returns raw encrypted text.
    """

    url = (
        BASE_URL
        + "/prematch/getmixedsportsandeventswithoutright"
    )

    params = {
        "sportId": 1,
        "tournamentId": tournament_id,
        "langId": 4,
        "partnerId": 107,
        "countryCode": "KE",
    }

    response = session.get(
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        timeout=30,
    )

    response.raise_for_status()

    return response.text