from parsers.betkanyon.browser import BetkanyonBrowser
import time

browser = BetkanyonBrowser()

browser.open()

print("Opening sportsbook...")

browser.goto("https://betkanyon1617.com/tr/sport/prematchevents/29324")

time.sleep(10)

print("\n==================== FRAMES ====================\n")

for i, frame in enumerate(browser.page.frames):

    print(f"FRAME {i}")
    print("URL :", frame.url)
    print()

browser.close()