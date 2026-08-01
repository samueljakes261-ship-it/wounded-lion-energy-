import re
import time
from pathlib import Path

from parsers.betkanyon.browser import BetkanyonBrowser

SAVE_DIR = Path("experiments/betkanyon/scripts")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

browser = BetkanyonBrowser()
browser.open()

page = browser.page

counter = 0


def sanitize(name):
    return re.sub(r'[^a-zA-Z0-9_.-]', "_", name)


def save_response(response):
    global counter

    try:
        url = response.url

        if ".js" not in url.lower():
            return

        body = response.text()

        filename = url.split("/")[-1].split("?")[0]

        if not filename.endswith(".js"):
            filename += ".js"

        filename = sanitize(filename)

        out = SAVE_DIR / f"{counter:04d}_{filename}"

        out.write_text(body, encoding="utf-8")

        print(f"[{counter:04d}] {filename}")

        counter += 1

    except Exception as e:
        print("FAILED:", e)


page.on("response", save_response)

print("Opening sportsbook...")

browser.goto("https://betkanyon1617.com/tr/sport/prematchevents/29324")

print("Waiting 30 seconds...")

time.sleep(30)

browser.close()

print("\nDone.")