import time
import json

from browser.sessions.scrapfly import ScrapflySession
from browser.cdp.client import CDPClient


def main():

    session = ScrapflySession()
    client = CDPClient(session.websocket_url())

    print("Connecting...")
    client.connect()
    print("Connected.\n")

    version = client.send("Browser.getVersion")
    print("Browser:", version["result"]["product"])

    target = client.send(
        "Target.createTarget",
        {
            "url": "about:blank"
        }
    )

    target_id = target["result"]["targetId"]

    attached = client.send(
        "Target.attachToTarget",
        {
            "targetId": target_id,
            "flatten": True
        }
    )

    session_id = attached["result"]["sessionId"]
    client.set_session(session_id)

    client.send("Page.enable")
    client.send("Network.enable")

    print("\nNavigating to Orbit...\n")

    client.send(
        "Page.navigate",
        {
            "url": "https://orbitxch.com/"
        }
    )

    print("Collecting responses for 10 seconds...\n")

    end = time.time() + 10

    while time.time() < end:

        message = json.loads(client.ws.recv())

        if message.get("method") == "Network.responseReceived":

            params = message["params"]

            request_id = params["requestId"]

            response = params["response"]

            mime = response.get("mimeType", "")
            url = response.get("url", "")

            print("=" * 80)
            print(url)
            print("Mime:", mime)

            if (
                "json" in mime.lower()
                or "javascript" not in mime.lower()
            ):

                try:

                    body = client.send(
                        "Network.getResponseBody",
                        {
                            "requestId": request_id
                        }
                    )

                    if "result" in body:

                        text = body["result"]["body"]

                        print("\nBODY PREVIEW\n")

                        print(text[:1000])

                except Exception as e:

                    print("Could not fetch body:", e)

    client.close()

    print("\nFinished.")


if __name__ == "__main__":
    main()