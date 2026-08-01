import json

with open("decrypted_output.json", encoding="utf-8") as f:
    events = json.load(f)

markets = {}

for event in events:
    # recursively search for market objects
    def walk(obj):
        if isinstance(obj, dict):
            if "GN" in obj:
                gid = obj.get("GId")
                gn = obj.get("GN")
                markets[gid] = gn

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(event)

print("\n===== UNIQUE MARKETS =====\n")

for gid, name in sorted(markets.items()):
    print(f"{gid:>5}   {name}")