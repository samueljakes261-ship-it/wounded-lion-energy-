from pathlib import Path

from parsers.betkanyon.browser import BetkanyonBrowser

URL = "https://sport.bksp3.com/js/partner/bootstrapper.min.js?v=1.2807.2026.1002"

browser = BetkanyonBrowser()

browser.open()

print("Downloading bootstrapper...")

result = browser.evaluate(
    f"""
    async () => {{
        const r = await fetch("{URL}");

        return {{
            status: r.status,
            text: await r.text()
        }};
    }}
    """
)

print("Status:", result["status"])

Path("experiments/betkanyon").mkdir(parents=True, exist_ok=True)

with open(
    "experiments/betkanyon/bootstrapper.min.js",
    "w",
    encoding="utf-8",
) as f:
    f.write(result["text"])

print("Saved.")

browser.close()