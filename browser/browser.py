from browser.sessions.zenrows import ZenRowsSession


class OrbitBrowser:

    def __init__(self):

        self.session = ZenRowsSession()

        self.browser = None
        self.context = None
        self.page = None

    def open(self):

        self.browser = self.session.connect()

        contexts = self.browser.contexts

        if contexts:
            self.context = contexts[0]
        else:
            self.context = self.browser.new_context()

        self.page = self.context.new_page()

    def goto(self, url):

        self.page.goto(
            url,
            wait_until="load",
            timeout=120000
        )

    def title(self):

        return self.page.title()

    def url(self):

        return self.page.url

    def html(self):

        return self.page.content()

    def close(self):

        self.session.close()