from pathlib import Path

from parsers.betkanyon.browser import BetkanyonBrowser

browser = BetkanyonBrowser()

browser.open()

browser.goto("https://betkanyon1617.com/tr/sport/prematchevents/29324")

Path("experiments/betkanyon/scripts").mkdir(
    parents=True,
    exist_ok=True,
)

scripts = browser.page.locator("script[src]")

count = scripts.count()

print()

print("Scripts:", count)

for i in range(count):

    src = scripts.nth(i).get_attribute("src")

    if not src:
        continue

    print(src)

    js = browser.page.evaluate(
        f"""
        async () => {{
            const r = await fetch("{src}");
            return await r.text();
        }}
        """
    )

    filename = src.split("/")[-1].split("?")[0]

    Path(
        f"experiments/betkanyon/scripts/{filename}"
    ).write_text(
        js,
        encoding="utf-8"
    )

browser.close()