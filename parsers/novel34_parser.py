from datetime import datetime

from models.match import MatchOdds


class Novel34Parser:
    """
    Parses Novel34 JSON into MatchOdds objects.
    """

    def parse(self, data: dict) -> list[MatchOdds]:

        matches = []

        for event in data["events"]:

            fixture = event["fixture"]

            prices = event["prices"]

            matches.append(

                MatchOdds(

                    bookmaker="Novel34",

                    competition=event["league"],

                    sport="Football",

                    market="Match Odds",

                    home_team=fixture["home"],

                    away_team=fixture["away"],

                    home_odds=prices["home"],

                    draw_odds=prices["draw"],

                    away_odds=prices["away"],

                    start_time=datetime.fromtimestamp(
                        fixture["kickoff"] / 1000
                    ),

                    collected_at=datetime.now()

                )

            )

        return matches