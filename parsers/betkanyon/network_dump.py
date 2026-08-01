from pathlib import Path
import time

from parsers.betkanyon.browser import BetkanyonBrowser

SAVE_DIR = Path("experiments/betkanyon/network")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

browser = BetkanyonBrowser()
browser.open()

page = browser.page

counter = 0


def save_response(response):
    global counter

    try:

        url = response.url

        # Ignore obvious static assets
        if any(
            ext in url
            for ext in [
                ".css",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".svg",
                ".woff",
                ".woff2",
                ".ttf",
                ".ico",
            ]
        ):
            return

        headers = response.headers
        content_type = headers.get("content-type", "")

        try:
            body = response.text()
        except:
            body = "<BINARY>"

        filename = SAVE_DIR / f"{counter:04d}.txt"

        filename.write_text(
            f"URL:\n{url}\n\n"
            f"STATUS:\n{response.status}\n\n"
            f"CONTENT-TYPE:\n{content_type}\n\n"
            f"BODY:\n{body}",
            encoding="utf-8",
            errors="ignore",
        )

        print(f"[{counter}] {response.status} {content_type} {url}")

        counter += 1

    except Exception as e:
        print("FAILED:", e)


page.on("response", save_response)

print("Opening sportsbook...")

browser.goto(
    "https://betkanyon1617.com/tr/sport/prematchevents/29324"
)

print("Waiting 30 seconds...")

time.sleep(30)

browser.close()

print("\nDone.")