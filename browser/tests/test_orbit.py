import time

from browser.browser import OrbitBrowser


def handle_frame(payload):
    """
    Print websocket frames that are likely
    to contain betting prices or markets.
    """

    try:
        text = str(payload)

        keywords = [
            "price",
            "prices",
            "market",
            "markets",
            "selection",
            "runner",
            "back",
            "lay",
            "odds",
            "decimal",
        ]

        if any(word in text.lower() for word in keywords):
            print("\n" + "=" * 100)
            print(text)
            print("=" * 100 + "\n")

    except Exception as e:
        print(f"Frame parsing error: {e}")


def attach_websocket(ws):

    print(f"\nWebSocket opened -> {ws.url}")

    ws.on(
        "framereceived",
        handle_frame
    )

    ws.on(
        "framesent",
        lambda payload: print(f"\nCLIENT -> {payload[:250]}")
    )


def main():

    print("\nOpening browser...\n")

    browser = OrbitBrowser()

    browser.open()

    page = browser.page

    print("Navigating to Orbit...\n")

    page.on(
        "websocket",
        attach_websocket
    )

    browser.goto("https://orbitxch.com")

    print("Waiting 30 seconds for websocket traffic...\n")

    time.sleep(30)

    print("\nFinished.")

    browser.close()


if __name__ == "__main__":
    main()