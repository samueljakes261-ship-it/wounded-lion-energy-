import time

from parsers.onwin.browser import OnwinBrowser


ONWIN_PAGE = (
    "https://onwin4505.com/"
    "sportsbook/live/main-line/soccer"
)


browser = OnwinBrowser()
page = browser.page()


def handle_request(request):
    url = request.url.lower()

    if "api-onwin" in url or "erisgaming" in url:
        print("\nREQUEST")
        print("-" * 100)
        print(request.method)
        print(request.url)


def handle_response(response):
    url = response.url.lower()

    if "api-onwin" in url or "erisgaming" in url:
        print("\nRESPONSE")
        print("-" * 100)
        print(response.status)
        print(response.url)


page.on("request", handle_request)
page.on("response", handle_response)


print("\nOpening OnWin...")
print("=" * 100)

try:
    page.goto(
        ONWIN_PAGE,
        wait_until="domcontentloaded",
        timeout=30000,
    )
except Exception as e:
    print(
        "\nNavigation finished with:",
        type(e).__name__,
        e,
    )


print("\nPage loaded:")
print(page.url)

print("\nListening for OnWin traffic.")
print("Leave this running for about 3-5 minutes.")
print("Do NOT close the browser.")
print("\n")


try:
    for i in range(300):
        page.wait_for_timeout(1000)

        if i % 10 == 0:
            print(
                f"Listening... {i} seconds"
            )

finally:
    print("\nStopping test...")

    browser.close()

    print("Done.")