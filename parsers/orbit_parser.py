from datetime import datetime

from models.match import MatchOdds


class OrbitParser:
    """
    Parses Orbit API JSON into MatchOdds objects.
    """

    def parse(self, data: dict) -> list[MatchOdds]:

        matches = []

        for market in data["marketCatalogues"]:

            runners = market["runners"]

            home = runners[0]
            away = runners[1]
            draw = runners[2]

            match = MatchOdds(

                bookmaker="Orbit Exchange",

                competition=market["competition"]["name"],

                sport="Football",

                market=market["marketName"],

                home_team=market["event"]["homeTeam"],

                away_team=market["event"]["awayTeam"],

                home_odds=home["price"],

                draw_odds=draw["price"],

                away_odds=away["price"],

                start_time=datetime.fromtimestamp(
                    market["marketStartTime"] / 1000
                ),

                collected_at=datetime.now()

            )

            matches.append(match)

        return matches