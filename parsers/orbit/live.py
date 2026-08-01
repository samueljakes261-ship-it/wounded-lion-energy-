import asyncio

from parsers.orbit.rest import get_live_markets
from parsers.orbit.client import OrbitWebSocketClient
from parsers.orbit.parser import OrbitParser


async def main():

    print("Fetching live markets...\n")

    data = get_live_markets()

    markets = data["marketCatalogueList"]["content"]

    print(f"Found {len(markets)} live markets.\n")

    ws = OrbitWebSocketClient()

    await ws.connect()

    print()

    for market in markets:

        market_id = market["marketId"]
        event_id = market["event"]["id"]
        match_name = market["event"]["name"]

        print("=" * 60)
        print(match_name)
        print("=" * 60)

        await ws.subscribe(
            market_id,
            event_id,
        )

        while True:

            raw = await ws.receive()

            if raw is None:
                continue

            parsed = OrbitParser.parse(raw)

            if parsed is None:
                continue

            print(parsed)

            break

    await ws.close()


if __name__ == "__main__":
    asyncio.run(main())