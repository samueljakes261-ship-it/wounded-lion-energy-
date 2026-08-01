from datetime import datetime

from models.match import MatchOdds


class OnWinParser:

    """
    Parses OnWin JSON into MatchOdds objects.
    """

    def parse(self, data: dict) -> list[MatchOdds]:

        matches = []

        for game in data["games"]:

            odds = game["markets"]

            matches.append(

                MatchOdds(

                    bookmaker="OnWin",

                    competition=game["leagueName"],

                    sport="Football",

                    market="Match Odds",

                    home_team=game["homeName"],

                    away_team=game["awayName"],

                    home_odds=odds["homeWin"],

                    draw_odds=odds["draw"],

                    away_odds=odds["awayWin"],

                    start_time=datetime.fromtimestamp(
                        game["kickoffTime"] / 1000
                    ),

                    collected_at=datetime.now()

                )

            )

        return matches