from simulator.base_simulator import BaseSimulator
from simulator.market.market_generator import MarketGenerator
from simulator.market.price_engine import PriceEngine

from simulator.profiles.profile_manager import ProfileManager


class BetfairSimulator(BaseSimulator):

    def __init__(self):

        super().__init__("Betfair")

        self.generator = MarketGenerator()
        self.engine = PriceEngine()

        self.profile = ProfileManager.get_profile("Betfair")

    def generate(self):

        markets = []

        for index, market in enumerate(self.generator.generate()):

            home_price, draw_price, away_price = self.engine.generate_prices(

                market.home_probability,
                market.draw_probability,
                market.away_probability,

                margin=0.03,
                variance=0.015,

                bookmaker="Betfair"

            )

            home_team = self.profile["teams"].get(
                market.home_team,
                market.home_team
            )

            away_team = self.profile["teams"].get(
                market.away_team,
                market.away_team
            )

            competition = self.profile["competitions"].get(
                market.competition,
                market.competition
            )

            markets.append({

                "marketId": f"1.{260000000 + index}",

                "marketName": "Match Odds",

                "marketStartTime": int(market.start_time.timestamp() * 1000),

                "competition": {

                    "name": competition

                },

                "event": {

                    "id": market.id,

                    "name": f"{home_team} v {away_team}",

                    "homeTeam": home_team,

                    "awayTeam": away_team

                },

                "runners": [

                    {

                        "runnerName": home_team,

                        "price": home_price

                    },

                    {

                        "runnerName": away_team,

                        "price": away_price

                    },

                    {

                        "runnerName": "The Draw",

                        "price": draw_price

                    }

                ]

            })

        self.export_json({

            "marketCatalogues": markets

        })