from browser.sessions.zenrows import ZenRowsSession


class BetkanyonBrowser:

    def __init__(self):

        self.session = ZenRowsSession()

        self.browser = None
        self.context = None
        self.page = None

    def connect(self):

        if self.browser is not None:
            return

        print("\nConnecting to ZenRows Browser...\n")

        self.browser = self.session.connect()

        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()

        self.page = self.context.new_page()

        print("Connected successfully.")

    def open_live_page(self):

        print("Opening BetKanyon live page...")

        self.page.goto(
            "https://betkanyon1617.com/tr/sport/live",
            wait_until="domcontentloaded",
            timeout=120000,
        )

        self.page.wait_for_timeout(5000)

        print("Live page loaded.")

    def reconnect(self):

        print("\nReconnecting browser...\n")

        self.close()

        self.connect()

        self.open_live_page()

    def close(self):

        try:

            if self.browser:

                self.session.close()

        finally:

            self.browser = None
            self.context = None
            self.page = None