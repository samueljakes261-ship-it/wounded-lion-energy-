import json
import os

from parsers.onwin.browser import OnwinBrowser


class OnwinFeed:

    ONWIN_PAGE = (
        "https://onwin4505.com/"
        "sportsbook/live/main-line/soccer"
    )

    TARGET = "get_main_line.erisgaming"

    OUTPUT_FILE = "output/onwin_main_line.json"

    # URL fragments we want to observe while investigating
    # OnWin's live-update mechanism.
    DEBUG_FRAGMENTS = (
        "api-onwin",
        "erisgaming",
        "update",
        "updates",
        "diff",
        "stream",
        "subscribe",
        "subscription",
        "/rpc/",
    )

    def __init__(self):
        self.browser = OnwinBrowser()
        self._matches = []

    def fetch(self):
        """
        Open OnWin through the persistent ZenRows browser.

        While capturing the known working main-line feed, also
        print relevant API traffic so we can identify whether
        OnWin sends a separate live-update/delta feed.
        """

        page = self.browser.page()

        captured = {
            "data": None
        }

        seen_debug_requests = set()

        def handle_request(request):
            """
            Observe relevant requests before they complete.
            """

            url = request.url.lower()

            if not any(
                fragment in url
                for fragment in self.DEBUG_FRAGMENTS
            ):
                return

            # Avoid printing the exact same URL repeatedly.
            if request.url in seen_debug_requests:
                return

            seen_debug_requests.add(request.url)

            print("\n" + "-" * 100)
            print("ONWIN REQUEST")
            print("-" * 100)

            print("METHOD:")
            print(request.method)

            print("\nURL:")
            print(request.url)

        def handle_request_finished(request):
            """
            Capture completed get_main_line.erisgaming responses.

            We use requestfinished because the response body should
            be completely available at this point.
            """

            # Stop processing once we already captured the feed.
            if captured["data"] is not None:
                return

            # Only capture the known main-line endpoint.
            if self.TARGET not in request.url:
                return

            print("\n" + "=" * 100)
            print("GET_MAIN_LINE REQUEST FINISHED")
            print("=" * 100)

            print("\nURL:")
            print(request.url)

            try:
                response = request.response()

                if response is None:
                    print("\nNo response object available.")
                    print("=" * 100)
                    return

                print("\nSTATUS:")
                print(response.status)

                if response.status != 200:
                    print(
                        "\nNot a 200 response. Ignoring."
                    )
                    print("=" * 100)
                    return

                body = response.body()

                print("\nRESPONSE SIZE:")
                print(len(body), "bytes")

                if not body:
                    print("\nResponse body is empty.")
                    print("=" * 100)
                    return

                try:
                    text = body.decode("utf-8")

                except UnicodeDecodeError:
                    text = body.decode(
                        "utf-8",
                        errors="replace"
                    )

                print("\nFIRST 1000 CHARACTERS:")
                print(text[:1000])

                try:
                    data = json.loads(text)

                except json.JSONDecodeError as e:
                    print(
                        "\nResponse was not valid JSON."
                    )
                    print(e)
                    print("=" * 100)
                    return

                captured["data"] = data

                print("\n" + "=" * 100)
                print("GET_MAIN_LINE CAPTURE SUCCESSFUL")
                print("=" * 100)

            except Exception as e:

                print(
                    "\nCould not read completed response:"
                )

                print(
                    type(e).__name__,
                    e
                )

                print("=" * 100)

        def handle_response(response):
            """
            Observe relevant responses as well.

            This is deliberately diagnostic only. We are not
            reading every response body because the main feed
            handler above already handles the large payload.
            """

            url = response.url.lower()

            if not any(
                fragment in url
                for fragment in self.DEBUG_FRAGMENTS
            ):
                return

            print("\n" + "-" * 100)
            print("ONWIN RESPONSE")
            print("-" * 100)

            print("STATUS:")
            print(response.status)

            print("\nURL:")
            print(response.url)

        # ------------------------------------------------------------------
        # IMPORTANT:
        # Attach ALL listeners before navigation.
        # ------------------------------------------------------------------

        page.on(
            "request",
            handle_request
        )

        page.on(
            "response",
            handle_response
        )

        page.on(
            "requestfinished",
            handle_request_finished
        )

        print("\nOpening Onwin...\n")

        try:
            page.goto(
                self.ONWIN_PAGE,
                wait_until="domcontentloaded",
                timeout=30000
            )

        except Exception as e:
            print(
                "\nNavigation finished with:",
                type(e).__name__,
                e
            )

        print("\nCurrent page:")
        print(page.url)

        print(
            "\nWaiting for "
            "get_main_line.erisgaming..."
        )

        print(
            "Waiting until the completed request "
            "is captured."
        )

        # ------------------------------------------------------------------
        # Wait for the initial main-line feed.
        # ------------------------------------------------------------------

        for i in range(120):

            if captured["data"] is not None:
                break

            try:
                page.wait_for_timeout(1000)

            except Exception as e:
                print(
                    "\nPage closed while waiting:",
                    type(e).__name__,
                    e
                )
                break

            if i % 10 == 0:
                print(
                    f"Still waiting... {i} seconds"
                )

        # ------------------------------------------------------------------
        # Remove listeners.
        # ------------------------------------------------------------------

        try:
            page.remove_listener(
                "request",
                handle_request
            )
        except Exception:
            pass

        try:
            page.remove_listener(
                "response",
                handle_response
            )
        except Exception:
            pass

        try:
            page.remove_listener(
                "requestfinished",
                handle_request_finished
            )
        except Exception:
            pass

        if captured["data"] is None:
            raise RuntimeError(
                "get_main_line.erisgaming completed "
                "but its JSON response was not captured "
                "within 120 seconds."
            )

        # ------------------------------------------------------------------
        # Save raw snapshot.
        # ------------------------------------------------------------------

        os.makedirs(
            os.path.dirname(self.OUTPUT_FILE),
            exist_ok=True
        )

        with open(
            self.OUTPUT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                captured["data"],
                f,
                indent=2,
                ensure_ascii=False
            )

        print(
            "\nSaved response to:"
        )
        print(self.OUTPUT_FILE)

        print(
            "\nSnapshot capture complete."
        )

        return captured["data"]

    def collect_once(self):
        """
        Capture one fresh OnWin feed and run it through
        the existing OnWin parser.

        Returns:
            list[MatchOdds]
        """

        raw_data = self.fetch()

        from parsers.onwin.parser import OnWinParser

        parser = OnWinParser()

        self._matches = parser.parse(raw_data)

        return self._matches

    def get_match_odds(self):
        """
        Return MatchOdds collected during the most recent
        collect_once() call.
        """

        return self._matches

    def close(self):
        """
        Close the persistent ZenRows browser session.
        """

        if self.browser is None:
            return

        try:
            self.browser.session.close()

        except Exception:
            pass

