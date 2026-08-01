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

        live = {}

        for runner in data.get("rc", []):

            live[runner["id"]] = RunnerOdds(

                selection_id=runner["id"],

                back=runner.get("catb", []),

                lay=runner.get("catl", []),

                traded_volume=runner.get("tv", 0),

            )

        ordered = []

        for runner in catalogue["runners"]:

            sid = runner["selectionId"]

            if sid in live:

                ordered.append(live[sid])

            else:

                ordered.append(

                    RunnerOdds(

                        selection_id=sid,

                        back=[],

                        lay=[],

                        traded_volume=0,

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