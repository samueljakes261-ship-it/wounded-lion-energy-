import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parsers.orbit_prematch.rest import get_upcoming_markets

markets = get_upcoming_markets()
print("ORBIT_PREMATCH_MARKETS", len(markets))
print("SAMPLE", markets[0]["marketId"], markets[0]["marketName"], (markets[0].get("event") or {}).get("name"))
