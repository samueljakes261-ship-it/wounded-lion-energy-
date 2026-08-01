import json
from pathlib import Path

LOG_FILE = Path("output/orbit_websocket_frames.txt")

KEYWORDS = [
    "price",
    "prices",
    "market",
    "markets",
    "marketId",
    "selection",
    "selectionId",
    "runner",
    "runnerId",
    "back",
    "lay",
    "odds",
    "subscribe",
    "eventId",
]


def main():

    if not LOG_FILE.exists():
        print("Log file not found.")
        return

    print(f"\nReading:\n{LOG_FILE}\n")

    lines = LOG_FILE.read_text(
        encoding="utf-8",
        errors="ignore"
    ).splitlines()

    matches = 0

    for line_number, line in enumerate(lines, start=1):

        lower = line.lower()

        if any(keyword.lower() in lower for keyword in KEYWORDS):

            matches += 1

            print("=" * 80)
            print(f"LINE {line_number}")
            print("=" * 80)
            print(line)

    print()
    print("=" * 80)
    print("TOTAL MATCHES:", matches)
    print("=" * 80)


if __name__ == "__main__":
    main()