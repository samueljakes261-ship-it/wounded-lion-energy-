import os

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()


class ZenRowsSession:
    def __init__(self):
        self.browser_ws = os.getenv("ZENROWS_BROWSER_WS")

        if not self.browser_ws:
            raise Exception("ZENROWS_BROWSER_WS missing from .env")

        self.playwright = None
        self.browser = None
        self.context = None
        self._page = None

    def connect(self):
        """
        Opens ONE persistent ZenRows browser session.
        If already connected, do nothing.
        """

        if self.browser is not None:
            return

        print("\nConnecting to ZenRows Browser...\n")

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.connect_over_cdp(
            self.browser_ws
        )

        # Reuse the default browser context if available
        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()

        print("Connected successfully.")

    def page(self):
        """
        Returns one persistent page.
        Creates it only once.
        """

        self.connect()

        if self._page is not None and not self._page.is_closed():
            return self._page

        self._page = self.context.new_page()

        return self._page

    def get_page(self):
        """
        Backwards compatibility with existing parsers.
        """

        return self.page()

    def capture_request_headers(self, url_contains):
        """
        Captures headers from browser requests whose URL contains
        the supplied text.

        Returns:
            dict: Captured request headers.

        Note:
            The listener must be installed before the request occurs.
        """

        self.connect()

        page = self.page()

        captured = {}

        def handle_request(request):
            if url_contains in request.url:
                print("\nMatching request detected:")
                print(request.url)

                captured.update(request.headers)

        page.on("request", handle_request)

        return captured

    def close(self):
        """
        Closes the browser session and Playwright connection.
        """

        if self._page and not self._page.is_closed():
            self._page.close()

        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()

        self._page = None
        self.context = None
        self.browser = None
        self.playwright = None