from simulator.base_simulator import BaseSimulator
from simulator.market.market_generator import MarketGenerator
from simulator.market.price_engine import PriceEngine


class Novel34Simulator(BaseSimulator):

    def __init__(self):

        super().__init__("Novel34")

        self.generator = MarketGenerator()
        self.engine = PriceEngine()

    def generate(self):

        events = []

        for market in self.generator.generate():

            home_price, draw_price, away_price = self.engine.generate_prices(

                market.home_probability,
                market.draw_probability,
                market.away_probability,

                margin=0.025,
                variance=0.020,

                bookmaker="Novel34"

            )

            events.append({

                "fixture": {

                    "id": market.id,

                    "home": market.home_team + " FC",

                    "away": market.away_team + " FC",

                    "kickoff": int(market.start_time.timestamp() * 1000)

                },

                "league": self._league_name(market.competition),

                "prices": {

                    "home": home_price,

                    "draw": draw_price,

                    "away": away_price

                }

            })

        self.export_json({

            "events": events

        })

    def _league_name(self, league):

        mapping = {

            "Premier League": "English Premier League",

            "La Liga": "Spanish Primera Division",

            "Turkish Super Lig": "Turkey Super League"

        }

        return mapping.get(league, league)