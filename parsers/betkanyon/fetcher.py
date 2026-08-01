from parsers.betkanyon.browser import BetkanyonBrowser


API = (
    "https://sport.bksp3.com/"
    "0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
    "/live/getliveevents"
    "?sportId=1"
    "&checkIsActiveAndBetStatus=false"
    "&stakeTypes=1"
    "&stakeTypes=702"
    "&stakeTypes=2"
    "&stakeTypes=3"
    "&stakeTypes=37"
    "&langId=4"
    "&partnerId=107"
    "&countryCode=KE"
)


class BetkanyonFetcher:

    def __init__(self):

        self.browser = None
        self.page = None
        self.initialized = False

    def _connect(self):

        print("\nConnecting browser...\n")

        self.browser = BetkanyonBrowser()

        self.browser.open()

        self.page = self.browser.page

        print("Opening live page...")

        self.browser.goto(
            "https://betkanyon1617.com/tr/sport/live"
        )

        #
        # Give the site time to initialize all cookies,
        # Cloudflare tokens and JS.
        #
        self.browser.wait(5000)

        print("Browser ready.\n")

        self.initialized = True

    def _reset_browser(self):

        print("\nBrowser connection lost. Reconnecting...\n")

        try:

            if self.browser:

                self.browser.close()

        except Exception:
            pass

        self.browser = None
        self.page = None
        self.initialized = False

        self._connect()

    def fetch(self):

        if not self.initialized:

            self._connect()

        for attempt in range(5):

            print(
                f"Fetching encrypted payload (attempt {attempt + 1}/5)..."
            )

            try:

                payload = self.page.evaluate(
                    """
                    async (url) => {

                        const response = await fetch(url, {
                            credentials: "include"
                        });

                        const json = await response.json();

                        return json.payload;

                    }
                    """,
                    API,
                )

                if payload:

                    print(f"Payload length: {len(payload)}")

                    return payload

            except Exception as e:

                print(f"Fetch failed: {e}")

                message = str(e).lower()

                #
                # Browser/page died -> reconnect automatically.
                #
                if (
                    "target page" in message
                    or "browser has been closed" in message
                    or "context has been closed" in message
                    or "socket hang up" in message
                    or "websocket" in message
                    or "connection closed" in message
                    or "epipe" in message
                ):

                    self._reset_browser()

                    continue

            #
            # Wait a little before retrying.
            #
            self.browser.wait(3000)

        raise TimeoutError(
            "Timed out waiting for BetKanyon payload."
        )

    def close(self):

        if self.browser:

            self.browser.close()