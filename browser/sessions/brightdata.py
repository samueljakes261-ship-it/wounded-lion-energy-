import os

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


load_dotenv()


class BrightDataSession:

    def __init__(self):

        self.username = os.getenv("BRIGHTDATA_USERNAME")
        self.password = os.getenv("BRIGHTDATA_PASSWORD")

        if not self.username:
            raise Exception("BRIGHTDATA_USERNAME missing from .env")

        if not self.password:
            raise Exception("BRIGHTDATA_PASSWORD missing from .env")

        self.playwright = None
        self.browser = None

    def connect(self):

        browser_ws = (
            f"wss://{self.username}:{self.password}"
            "@brd.superproxy.io:9222"
        )

        print("\nConnecting to Bright Data Browser...\n")

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.connect_over_cdp(
            browser_ws
        )

        print("Connected successfully.")

        return self.browser

    def close(self):

        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()