from parsers.onwin.browser import OnwinBrowser


browser = OnwinBrowser()
page = browser.page()


def on_request(request):
    print("[REQUEST]", request.method, request.url)


def on_response(response):
    print("[RESPONSE]", response.status, response.url)


page.on("request", on_request)
page.on("response", on_response)

print("\nOpening Onwin...\n")

try:
    page.goto(
        "https://onwin4505.com/sportsbook/live/main-line/soccer",
        wait_until="domcontentloaded",
        timeout=60000
    )
except Exception as e:
    print("\nNavigation warning:")
    print(e)

print("\nPage URL:")
print(page.url)

print("\nListening for ALL network requests.")
print("Now interact with the browser if possible.")
print("Press ENTER to stop.\n")

input()

browser.session.close()