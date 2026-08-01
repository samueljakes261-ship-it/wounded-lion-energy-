from simulator.base_simulator import BaseSimulator
from simulator.market.market_generator import MarketGenerator
from simulator.market.price_engine import PriceEngine


class Kolay90Simulator(BaseSimulator):

    def __init__(self):

        super().__init__("Kolay90")

        self.generator = MarketGenerator()
        self.engine = PriceEngine()

    def generate(self):

        matches = []

        for index, market in enumerate(self.generator.generate()):

            home_price, draw_price, away_price = self.engine.generate_prices(

                market.home_probability,
                market.draw_probability,
                market.away_probability,

                margin=0.04,
                variance=0.025,

                bookmaker="Kolay90"

            )

            matches.append({

                "match_id": f"KY{1000 + index}",

                "league": f"England {market.competition}",

                "match": {

                    "home": market.home_team.upper(),

                    "away": market.away_team.upper()

                },

                "kickoff": int(

                    market.start_time.timestamp() * 1000

                ),

                "markets": {

                    "1X2": {

                        "home": home_price,

                        "draw": draw_price,

                        "away": away_price

                    }

                }

            })

        self.export_json({

            "matches": matches

        })