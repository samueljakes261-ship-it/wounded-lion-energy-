from playwright.sync_api import sync_playwright

from credentials.zenrows_provider import connect_with_failover


class ZenRowsSession:
    """
    Opens a ZenRows Scraping Browser session via CredentialManager
    (credentials/zenrows_provider.py), which automatically fails over
    to another authorized ZenRows credential if the current one
    becomes unusable. Callers never need to know which credential is
    active -- see self.credential_id if needed for diagnostics (never
    log the secret itself).
    """

    def __init__(self):

        self.playwright = None
        self.browser = None
        self.credential_id = None

    def connect(self):

        print("\nConnecting to ZenRows Browser...\n")

        self.playwright = sync_playwright().start()

        try:
            self.browser, self.credential_id = connect_with_failover(
                self.playwright
            )
        except Exception:
            # Playwright Sync starts a hidden asyncio loop on this
            # thread. If connect_with_failover raises before we have a
            # browser (credentials cooling down, CDP handshake fail),
            # that loop must be stopped or the next retry on this same
            # thread raises "Sync API inside the asyncio loop" and
            # BetKanyon can never recover without a process restart.
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
            self.browser = None
            self.credential_id = None
            raise

        print("Connected successfully.")

        return self.browser

    def close(self):

        if self.browser:
            self.browser.close()

        if self.playwright:
            self.playwright.stop()

        self.browser = None
        self.playwright = None
        self.credential_id = None