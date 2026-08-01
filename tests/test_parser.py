import json

from parsers.orbit.parser import OrbitParser


with open("tests/sample_market.json", encoding="utf-8") as f:
    raw = json.load(f)

message = json.dumps(raw)

market = OrbitParser.parse(message)

print()

print("Market ID:", market.market_id)
print("Event ID :", market.event_id)
print("Status   :", market.market_status)
print()

for runner in market.runners:

    print("Selection:", runner.selection_id)
    print("Back:", runner.back)
    print("Lay :", runner.lay)
    print()