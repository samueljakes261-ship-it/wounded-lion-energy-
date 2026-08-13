import json

from .models import MarketOdds
from .models import RunnerOdds


class OrbitParser:

    @staticmethod
    def parse(message, catalogue):

        # websocket payload

        if isinstance(message, str):
            data = json.loads(message)
        else:
            data = message

        # "rc" entries carry price data only (no runner name) -- keyed
        # by selection id so it can be paired with the catalogue's
        # runner name/order below.
        live = {}

        for runner in data.get("rc", []):

            live[runner["id"]] = runner

        ordered = []

        for runner in catalogue["runners"]:

            sid = runner["selectionId"]

            rc = live.get(sid)

            ordered.append(

                RunnerOdds(

                    selection_id=sid,

                    name=runner.get("runnerName"),

                    # "bdatb"/"bdatl" ("book data available to
                    # back/lay") each carry an explicit "index" (0 =
                    # best price for that side) alongside "odds" and
                    # "amount" (liquidity size) -- unlike "catb"/"catl",
                    # which are plain [price, size] pairs sorted purely
                    # by ascending numeric price. Ascending-by-price
                    # order means index 0 of "catb" is actually the
                    # WORST back price (best back = highest price), so
                    # using it as "top price" silently returned the
                    # wrong price level. "catl" happened to look
                    # correct (ascending == best-first for LAY, since
                    # best lay = lowest price) which is exactly the
                    # kind of order-position assumption that must not
                    # be trusted -- see parsers/orbit/adapter.py.
                    back=rc.get("bdatb", []) if rc else [],

                    lay=rc.get("bdatl", []) if rc else [],

                    traded_volume=rc.get("tv", 0) if rc else 0,

                )

            )

        definition = data["marketDefinition"]

        return MarketOdds(

            market_id=data["id"],

            event_id=definition["eventId"],

            market_status=definition["status"],

            in_play=definition["inPlay"],

            runners=ordered,

            home_team=catalogue["event"]["homeTeam"],

            away_team=catalogue["event"]["awayTeam"],

            competition=catalogue["competition"]["name"],

            sport=catalogue["eventType"]["name"],

            market_name=catalogue["marketName"],

            start_time=catalogue["marketStartTime"],

            total_matched=catalogue["totalMatched"],

        )