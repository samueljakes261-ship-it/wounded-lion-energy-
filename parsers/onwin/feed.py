import json
import os
import time

from parsers.onwin.browser import OnwinBrowser
from parsers.onwin.state import OnwinState


class OnwinFeed:

    ONWIN_PAGE = (
        "https://onwin4505.com/"
        "sportsbook/live/main-line/soccer"
    )

    TARGET = "get_main_line.erisgaming"

    # The continuously-changing update feed. Same session/page as
    # TARGET above -- never fetched by opening a separate browser.
    UPDATE_TARGET = "find_event_snapshots.erisgaming"

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

        # Persistent-mode fields (used by start()/poll(), see below).
        # These are intentionally separate from the legacy
        # fetch()/collect_once() one-shot flow so that flow keeps
        # working unmodified for existing diagnostic scripts.
        self.state = OnwinState()
        self._page = None
        self._on_change = None
        self._on_update = None
        self._initial_captured = False
        self._last_update_at = None
        self._closing = False

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

        self._closing = True

        try:
            self.browser.session.close()

        except Exception:
            pass

        self._page = None

    # ------------------------------------------------------------------
    # PERSISTENT MODE
    #
    # start() opens the browser/page ONCE, attaches the get_main_line
    # (one-shot) and find_event_snapshots (continuous) listeners BEFORE
    # navigating, navigates ONCE, and builds local state from the
    # initial snapshot. After start() returns, the caller keeps calling
    # poll() in a loop -- no further navigation or main-line downloads
    # happen; find_event_snapshots responses are handled as they arrive
    # and patched straight into self.state.
    # ------------------------------------------------------------------

    def start(self, on_change=None, on_update=None, timeout=180):
        """
        Open the browser/page once, capture get_main_line once, build
        local state, and leave the page open with a live listener for
        find_event_snapshots.

        Args:
            on_change: optional callable(set[str]) invoked with the set
                of changed event_ids whenever an update response
                actually changes local state (i.e. NOT called for a
                response that changed nothing).
            on_update: optional callable(version, event_count,
                changed_count) invoked for EVERY successfully processed
                update response, whether or not it changed anything --
                intended for lightweight status logging, not for
                deciding whether to republish MatchOdds (see on_change).
            timeout: seconds to wait for the initial get_main_line
                capture before giving up.

        Returns:
            The initialized OnwinState.
        """

        self._on_change = on_change
        self._on_update = on_update
        self._initial_captured = False

        page = self.browser.page()
        self._page = page

        initial_box = {"data": None}

        def handle_main_line(request):
            # Only needed once: after the initial snapshot is captured
            # we no longer care about further get_main_line requests
            # (the update feed takes over from here).
            if self._initial_captured:
                return

            if self.TARGET not in request.url:
                return

            try:
                response = request.response()

                if response is None or response.status != 200:
                    return

                body = response.body()

                if not body:
                    return

                data = json.loads(body.decode("utf-8", errors="replace"))

            except Exception as exc:
                print(
                    "\n[OnwinFeed] Failed to read get_main_line response:",
                    type(exc).__name__,
                    exc,
                )
                return

            initial_box["data"] = data
            self._initial_captured = True

        def handle_update(response):
            if self.UPDATE_TARGET not in response.url:
                return

            self._handle_update_response(response)

        # Attach BOTH listeners before navigating so no early responses
        # are missed.
        page.on("requestfinished", handle_main_line)
        page.on("response", handle_update)

        print("\n[OnwinFeed] Navigating to OnWin (once)...")

        page.goto(
            self.ONWIN_PAGE,
            wait_until="domcontentloaded",
            timeout=30000,
        )

        started_at = time.monotonic()

        while initial_box["data"] is None:

            if time.monotonic() - started_at > timeout:
                raise RuntimeError(
                    f"get_main_line.erisgaming was not captured within "
                    f"{timeout} seconds."
                )

            if page.is_closed():
                raise RuntimeError(
                    "OnWin page closed while waiting for get_main_line."
                )

            page.wait_for_timeout(500)

        load_started = time.monotonic()
        event_ids = self.state.load_initial(initial_box["data"])
        load_seconds = time.monotonic() - load_started

        self._last_update_at = time.monotonic()

        print(
            f"\n[OnwinFeed] Initial snapshot loaded: "
            f"{len(event_ids)} football events tracked "
            f"(parsed in {load_seconds:.3f}s, "
            f"version={self.state.last_version})."
        )

        return self.state

    def _handle_update_response(self, response):
        """
        Process one find_event_snapshots.erisgaming response: patch it
        into self.state and, if anything actually changed, notify
        on_change with the affected event_ids.

        This never writes the response to disk and never re-parses the
        full main-line tree -- it only walks whatever (comparatively
        small) payload this single response contains.
        """

        if self._closing:
            # We're shutting down -- the page/context may already be
            # gone, so reading the body would just raise a noisy
            # TargetClosedError for a response we don't care about.
            return

        try:
            if response.status != 200:
                return

            body = response.body()

            if not body:
                return

            data = json.loads(body.decode("utf-8", errors="replace"))

        except Exception as exc:
            print(
                "\n[OnwinFeed] Failed to read update response:",
                type(exc).__name__,
                exc,
            )
            return

        self._last_update_at = time.monotonic()

        try:
            changed = self.state.apply_update(data)
        except Exception as exc:
            print(
                "\n[OnwinFeed] Failed to apply update:",
                type(exc).__name__,
                exc,
            )
            return

        if self._on_update is not None:
            try:
                self._on_update(
                    self.state.last_version,
                    self.state.last_update_event_count,
                    len(changed),
                )
            except Exception as exc:
                print(
                    "\n[OnwinFeed] on_update callback failed:",
                    type(exc).__name__,
                    exc,
                )

        if changed and self._on_change is not None:
            try:
                self._on_change(changed)
            except Exception as exc:
                print(
                    "\n[OnwinFeed] on_change callback failed:",
                    type(exc).__name__,
                    exc,
                )

    def poll(self, tick_ms=500):
        """
        Keep the browser's message loop pumping so queued
        request/response events (including find_event_snapshots) are
        actually delivered to their handlers.

        This does not navigate, fetch, or parse anything by itself --
        it's the same wait_for_timeout-based keep-alive pattern already
        proven in test_onwin_updates.py.
        """

        if self._page is None or self._page.is_closed():
            raise RuntimeError("OnwinFeed.poll() called with no open page.")

        self._page.wait_for_timeout(tick_ms)

    def is_alive(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    def seconds_since_last_update(self):
        if self._last_update_at is None:
            return None

        return time.monotonic() - self._last_update_at

