from browser.sessions.scrapfly import ScrapflySession
from browser.cdp.client import CDPClient


class OrbitBrowser:

    HOME = "https://orbitxch.com/"

    def __init__(self):

        session = ScrapflySession()

        self.client = CDPClient(
            session.websocket_url()
        )

    def connect(self):

        self.client.connect()

        target = self.client.create_target()

        self.client.attach(target)

        self.client.enable_page()

        self.client.enable_network()

    def goto_homepage(self):

        self.client.navigate(self.HOME)

    def title(self):

        result = self.client.evaluate(
            "document.title"
        )

        return result["result"]["result"]["value"]

    def url(self):

        result = self.client.evaluate(
            "window.location.href"
        )

        return result["result"]["result"]["value"]

    def html(self):

        document = self.client.get_document()

        node = document["result"]["root"]["nodeId"]

        html = self.client.get_outer_html(node)

        return html["result"]["outerHTML"]

    def close(self):

        self.client.close()