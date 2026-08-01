from datetime import datetime, timedelta

from simulator.market.market import Market


class MarketGenerator:

    def generate(self):

        kickoff = datetime.now() + timedelta(hours=2)

        return [

            Market(

                id="M001",

                sport="Football",

                competition="Premier League",

                home_team="Liverpool",

                away_team="Chelsea",

                start_time=kickoff,

                home_probability=0.42,

                draw_probability=0.27,

                away_probability=0.31,

            ),

            Market(

                id="M002",

                sport="Football",

                competition="Premier League",

                home_team="Arsenal",

                away_team="Tottenham",

                start_time=kickoff,

                home_probability=0.46,

                draw_probability=0.25,

                away_probability=0.29,

            ),

            Market(

                id="M003",

                sport="Football",

                competition="La Liga",

                home_team="Barcelona",

                away_team="Real Madrid",

                start_time=kickoff,

                home_probability=0.38,

                draw_probability=0.28,

                away_probability=0.34,

            ),

            Market(

                id="M004",

                sport="Football",

                competition="Turkish Super Lig",

                home_team="Galatasaray",

                away_team="Fenerbahce",

                start_time=kickoff,

                home_probability=0.41,

                draw_probability=0.26,

                away_probability=0.33,

            )

        ]