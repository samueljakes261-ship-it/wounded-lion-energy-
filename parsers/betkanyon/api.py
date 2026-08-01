from parsers.betkanyon.browser import BetkanyonBrowser

BASE = "https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"

HOME_PAGE = (
    BASE +
    "/Tools/RequestHelper?parent=betkanyon1617.com"
)


class BetkanyonAPI:

    def __init__(self):

        self.browser = BetkanyonBrowser()

        self.browser.open()

    def initialize(self):

        print("Opening Betkanyon...")

        self.browser.goto(HOME_PAGE)

        print("Browser ready.")

    def fetch_tournaments(self):

        endpoint = (
            BASE
            + "/prematch/gettournaments"
            + "?sportId=1"
            + "&langId=4"
            + "&partnerId=107"
            + "&countryCode=KE"
        )

        print()
        print("Fetching tournament list...")

        result = self.browser.evaluate(
            f"""
            async () => {{

                const response = await fetch("{endpoint}");

                return await response.text();

            }}
            """
        )

        return result

    def fetch_matches(self, tournament_id):

        endpoint = (
            BASE
            + "/prematch/getmixedsportsandeventswithoutright"
            + f"?sportId=1&tournamentId={tournament_id}"
            + "&langId=4"
            + "&partnerId=107"
            + "&countryCode=KE"
        )

        result = self.browser.evaluate(
            f"""
            async () => {{

                const response = await fetch("{endpoint}");

                return await response.text();

            }}
            """
        )

        return result

    def close(self):

        self.browser.close()