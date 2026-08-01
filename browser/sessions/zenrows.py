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

    def connect(self):

        print("\nConnecting to ZenRows Browser...\n")

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.connect_over_cdp(
            self.browser_ws
        )

        print("Connected successfully.")

        return self.browser

    def close(self):

        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()