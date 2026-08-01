from browser.sessions.zenrows import ZenRowsSession


class BetkanyonBrowser:

    def __init__(self):

        self.session = ZenRowsSession()

        self.browser = None
        self.context = None
        self.page = None

        self.responses = []

    def open(self):

        self.browser = self.session.connect()

        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()

        self.page = self.context.new_page()

        self.page.on(
            "response",
            lambda response: self.responses.append(response)
        )

    def goto(self, url):

        self.page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=120000,
        )

    def wait(self, milliseconds):

        self.page.wait_for_timeout(milliseconds)

    def evaluate(self, script):

        return self.page.evaluate(script)

    def title(self):

        return self.page.title()

    def url(self):

        return self.page.url

    def html(self):

        return self.page.content()

    def close(self):

        self.session.close()