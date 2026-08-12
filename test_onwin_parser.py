import json

from parsers.onwin.parser import OnwinParser


print("\nLoading Onwin snapshot...")

with open(
    "output/onwin_main_line.json",
    "r",
    encoding="utf-8"
) as f:

    data = json.load(f)


parser = OnwinParser()

events = parser.parse_live_football(data)


print("\n" + "=" * 80)
print("LIVE FOOTBALL EVENTS")
print("=" * 80)

print("\nTotal live football events:", len(events))


for index, event in enumerate(events, start=1):

    print("\n" + "-" * 80)

    print(f"EVENT #{index}")

    print(
        event["team1"]["name"],
        "vs",
        event["team2"]["name"]
    )

    print("Category:", event["category"])
    print("Tournament:", event["tournament"])
    print("Event ID:", event["event_id"])
    print("Status:", event["status"])
    print("Odds:", event["odds"])
    print("Scores:", event["scores"])