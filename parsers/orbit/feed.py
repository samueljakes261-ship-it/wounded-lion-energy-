from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.client import OrbitWebSocketClient
from parsers.orbit.parser import OrbitParser
from parsers.orbit.rest import get_all_live_markets


class OrbitFeed:

    def __init__(self):

        self.matches = []

    async def collect_once(self):

        client = OrbitWebSocketClient()

        markets = get_all_live_markets()

        catalogue = {}

        for market in markets:

            catalogue[market["marketId"]] = market

        await client.connect()

        for market in markets:

            await client.subscribe(
                market["marketId"],
                market["event"]["id"],
            )

        collected = {}

        expected = len(markets)

        received = 0

        while received < expected:

            raw = await client.receive()

            if raw is None:
                continue

            if (
                "marketDefinition" not in raw
                or "id" not in raw
            ):
                continue

            market_id = raw["id"]

            if market_id not in catalogue:
                continue

            parsed = OrbitParser.parse(
                raw,
                catalogue[market_id],
            )

            match = OrbitAdapter.to_match_odds(parsed)

            if match:

                collected[market_id] = match

            received += 1

        await client.close()

        self.matches = list(collected.values())

        #
        # DEBUG
        #
        print("\n================ ORBIT MATCHES ================\n")

        for match in self.matches:

            print(match)
            print()

        return self.matches

    def get_match_odds(self):

        return self.matches