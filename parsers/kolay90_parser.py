from datetime import datetime

from models.match import MatchOdds


class Kolay90Parser:
    """
    Converts Kolay90 JSON into MatchOdds objects.
    """

    def parse(self, data: dict) -> list[MatchOdds]:

        matches = []

        for item in data["matches"]:

            odds = item["markets"]["1X2"]

            match = MatchOdds(

                bookmaker="Kolay90",

                competition=item["league"],

                sport="Football",

                market="Match Odds",

                home_team=item["match"]["home"],

                away_team=item["match"]["away"],

                home_odds=odds["home"],

                draw_odds=odds["draw"],

                away_odds=odds["away"],

                start_time=datetime.fromtimestamp(
                    item["kickoff"] / 1000
                ),

                collected_at=datetime.now()

            )

            matches.append(match)

        return matches