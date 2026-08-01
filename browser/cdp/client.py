import json
import websocket


class CDPClient:

    def __init__(self, websocket_url):

        self.websocket_url = websocket_url
        self.ws = None
        self.message_id = 0
        self.session_id = None

    def connect(self):

        self.ws = websocket.create_connection(
            self.websocket_url,
            timeout=30
        )

    def close(self):

        if self.ws:
            self.ws.close()

    def send(self, method, params=None):

        if params is None:
            params = {}

        self.message_id += 1

        message = {
            "id": self.message_id,
            "method": method,
            "params": params
        }

        if self.session_id:
            message["sessionId"] = self.session_id

        self.ws.send(json.dumps(message))

        while True:

            response = json.loads(self.ws.recv())

            if response.get("id") == self.message_id:
                return response

    def set_session(self, session_id):

        self.session_id = session_id

    # -------------------------------------------------
    # Browser helpers
    # -------------------------------------------------

    def create_target(self, url="about:blank"):

        response = self.send(
            "Target.createTarget",
            {"url": url}
        )

        return response["result"]["targetId"]

    def attach(self, target_id):

        response = self.send(
            "Target.attachToTarget",
            {
                "targetId": target_id,
                "flatten": True
            }
        )

        session = response["result"]["sessionId"]

        self.set_session(session)

        return session

    def enable_page(self):

        return self.send("Page.enable")

    def enable_network(self):

        return self.send("Network.enable")

    def navigate(self, url):

        return self.send(
            "Page.navigate",
            {"url": url}
        )

    def get_document(self):

        return self.send(
            "DOM.getDocument",
            {"depth": 0}
        )

    def get_outer_html(self, node_id):

        return self.send(
            "DOM.getOuterHTML",
            {"nodeId": node_id}
        )

    def evaluate(self, javascript):

        return self.send(
            "Runtime.evaluate",
            {
                "expression": javascript,
                "returnByValue": True
            }
        )