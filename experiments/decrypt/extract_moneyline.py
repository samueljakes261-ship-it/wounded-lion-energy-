import json


# Change this to your decrypted file
INPUT_FILE = "decrypted_output.json"


def find_moneyline_market(markets):
    """
    Looks for the 3-way Match Winner market.
    """

    for market in markets:

        gid = market.get("GId")
        name = (market.get("GN") or "").lower()

        if gid == 1:
            return market

        if "maç sonucu" in name:
            return market

        if "match result" in name:
            return market

    return None


def extract_odds(market):

    odds = {}

    for stake in market.get("Stakes", []):

        stake_name = (stake.get("N") or "").strip()

        price = stake.get("F")

        if stake_name == "1":
            odds["home"] = price

        elif stake_name in ["X", "Draw"]:
            odds["draw"] = price

        elif stake_name == "2":
            odds["away"] = price

    return odds


with open(INPUT_FILE, encoding="utf-8") as f:
    data = json.load(f)

events = data if isinstance(data, list) else data.get("Events", [])

print("=" * 80)

for event in events:

    home = event.get("HT")
    away = event.get("AT")

    event_name = event.get("N")

    market = find_moneyline_market(event.get("Markets", []))

    if market is None:
        continue

    odds = extract_odds(market)

    if not odds:
        continue

    print(event_name)
    print(" Home :", odds.get("home"))
    print(" Draw :", odds.get("draw"))
    print(" Away :", odds.get("away"))
    print("-" * 60)