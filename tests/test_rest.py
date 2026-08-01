from parsers.orbit.rest import get_live_markets


data = get_live_markets()

markets = data["marketCatalogueList"]["content"]

print()

print(f"Found {len(markets)} live markets")

print()

for market in markets[:10]:

    print("-----------------------------------")

    print("Match :", market["event"]["name"])

    print("Market:", market["marketId"])

    print("Event :", market["event"]["id"])