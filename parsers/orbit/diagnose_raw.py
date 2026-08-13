"""
Orbit data-accuracy validation tool.

Connects to Orbit, subscribes to a handful of live 1-X-2 markets, and
for each incoming price frame prints a side-by-side comparison of:

  RAW    -- ground truth, straight from Orbit's own "bdatb"/"bdatl"
            ladders (index 0 = Orbit's own explicit "best price"
            marker for that side).
  PARSED -- what parsers/orbit/parser.py + parsers/orbit/adapter.py
            (the actual production pipeline) currently produce.
  OLD    -- what the pre-fix code would have produced (positional
            [home, draw, away] unpacking + catb/catl[0][0]), shown
            only when it disagrees with RAW, to make the historical
            bug visible.

This is throwaway/manual investigation & validation tooling, not part
of the production pipeline -- run manually and read the output.
"""

import asyncio

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.client import OrbitWebSocketClient
from parsers.orbit.parser import OrbitParser
from parsers.orbit.rest import get_all_live_markets


MARKETS_TO_WATCH = 6
FRAMES_TO_CAPTURE = 10


def _old_top_price(ladder_pairs):
    return ladder_pairs[0][0] if ladder_pairs else None


def _validate_against_old_code(market_dict, catalogue):
    """
    Reproduce the OLD (buggy) parsing path directly against the raw
    catalogue + market dict, for comparison purposes only.
    """
    runners_by_id = {r["selectionId"]: r for r in catalogue["runners"]}
    rc_by_id = {rc["id"]: rc for rc in market_dict.get("rc", [])}

    # OLD bug #1: positional unpacking assumed [home, draw, away].
    ordered_ids = [r["selectionId"] for r in catalogue["runners"]]
    if len(ordered_ids) != 3:
        return None
    old_home_id, old_draw_id, old_away_id = ordered_ids

    # OLD bug #2: top price = catb/catl[0][0] (ascending-sorted array,
    # not Orbit's own "index" marker).
    def old_price(sid, side_key):
        rc = rc_by_id.get(sid)
        if not rc:
            return None
        return _old_top_price(rc.get(side_key, []))

    return {
        "home_name": runners_by_id.get(old_home_id, {}).get("runnerName"),
        "draw_name": runners_by_id.get(old_draw_id, {}).get("runnerName"),
        "away_name": runners_by_id.get(old_away_id, {}).get("runnerName"),
        "home_back": old_price(old_home_id, "catb"),
        "draw_back": old_price(old_draw_id, "catb"),
        "away_back": old_price(old_away_id, "catb"),
    }


async def main():
    print("Fetching live markets...\n")
    markets = get_all_live_markets()

    three_runner = [m for m in markets if len(m.get("runners", [])) == 3]
    watch = three_runner[:MARKETS_TO_WATCH] or markets[:MARKETS_TO_WATCH]
    catalogue = {m["marketId"]: m for m in watch}

    client = OrbitWebSocketClient()
    await client.connect()

    for m in watch:
        await client.subscribe(m["marketId"], m["event"]["id"])

    print("\nListening for frames...\n")

    captured = 0
    seen_markets = set()

    while captured < FRAMES_TO_CAPTURE and len(seen_markets) < len(watch):
        raw = await client.receive()

        if raw is None:
            print("Socket closed.")
            break

        if "marketDefinition" not in raw or "id" not in raw:
            continue

        market_id = raw["id"]
        if market_id not in catalogue:
            continue

        cat = catalogue[market_id]

        parsed_market = OrbitParser.parse(raw, cat)
        back = OrbitAdapter.to_match_odds(parsed_market, side="BACK")
        lay = OrbitAdapter.to_match_odds(parsed_market, side="LAY")

        old = _validate_against_old_code(raw, cat)

        print("=" * 60)
        print("ORBIT DATA VALIDATION")
        print("=" * 60)
        print(f"Event: {cat['event']['name']}")
        print(f"Market: {cat.get('marketName')}  (id={market_id})")
        print()

        if back:
            print(
                f"PARSED BACK -> home={back.home_odds}  "
                f"draw={back.draw_odds}  away={back.away_odds}"
            )
        else:
            print("PARSED BACK -> not fully quoted yet")

        if lay:
            print(
                f"PARSED LAY  -> home={lay.home_odds}  "
                f"draw={lay.draw_odds}  away={lay.away_odds}"
            )
        else:
            print("PARSED LAY  -> not fully quoted yet")

        if old and back:
            mismatch = (
                old["home_back"] != back.home_odds
                or old["draw_back"] != back.draw_odds
                or old["away_back"] != back.away_odds
            )
            print(
                f"OLD (buggy) BACK -> "
                f"{old['home_name']}={old['home_back']}  "
                f"{old['draw_name']}={old['draw_back']}  "
                f"{old['away_name']}={old['away_back']}"
            )
            print("STATUS:", "MISMATCH (bug reproduced)" if mismatch else "matches new code")

        print()

        seen_markets.add(market_id)
        captured += 1

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
