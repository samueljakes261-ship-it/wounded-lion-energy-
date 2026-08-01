import json
import time

from parsers.betkanyon_v2.browser import BetkanyonBrowser


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

        self.browser = BetkanyonBrowser()

        self.connected = False

    def _ensure_browser(self):

        if self.connected:
            return

        self.browser.connect()

        self.browser.open_live_page()

        self.connected = True

    def fetch(self):

        self._ensure_browser()

        for attempt in range(5):

            print(f"Fetching payload (attempt {attempt+1}/5)...")

            try:

                payload = self.browser.page.evaluate(
                    """
                    async (url) => {

                        const response = await fetch(url, {
                            credentials: "include"
                        });

                        const text = await response.text();

                        return text;

                    }
                    """,
                    API,
                )

                #
                # Sometimes Cloudflare returns HTML instead of JSON.
                #
                if payload.startswith("<!DOCTYPE"):

                    raise Exception(
                        "Cloudflare HTML returned instead of JSON."
                    )

                #
                # ZenRows returns:
                #
                # {"payload":"....."}
                #
                data = json.loads(payload)

                encrypted = data.get("payload")

                if encrypted:

                    print(
                        f"Encrypted payload length: {len(encrypted)}"
                    )

                    return encrypted

                raise Exception("payload field missing.")

            except Exception as e:

                print(f"Fetch failed: {e}")

                #
                # Browser probably died.
                #
                try:

                    self.browser.reconnect()

                except Exception:

                    pass

                self.connected = False

                time.sleep(2)

                self._ensure_browser()

        raise Exception(
            "Unable to fetch BetKanyon payload after 5 attempts."
        )

    def close(self):

        self.browser.close()