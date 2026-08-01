from pathlib import Path

from dotenv import load_dotenv
from scrapfly import ScrapflyClient, BrowserConfig

import os


class ScrapflySession:

    def __init__(self):

        # Project root (.env lives here)
        project_root = Path(__file__).resolve().parents[2]

        load_dotenv(project_root / ".env")

        api_key = os.getenv("SCRAPFLY_API_KEY")

        if not api_key:
            raise RuntimeError("SCRAPFLY_API_KEY not found.")

        self.client = ScrapflyClient(key=api_key)

    def websocket_url(self):

        config = BrowserConfig()

        # Scrapfly SDK v0.11.x returns the websocket URL directly as a string.
        return self.client.cloud_browser(config)