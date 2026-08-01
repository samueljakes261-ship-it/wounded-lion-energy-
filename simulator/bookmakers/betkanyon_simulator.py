from simulator.base_simulator import BaseSimulator
from simulator.market.market_generator import MarketGenerator
from simulator.market.price_engine import PriceEngine


class BetKanyonSimulator(BaseSimulator):

    def __init__(self):

        super().__init__("BetKanyon")

        self.generator = MarketGenerator()
        self.engine = PriceEngine()

    def generate(self):

        fixtures = []

        for market in self.generator.generate():

            home_price, draw_price, away_price = self.engine.generate_prices(

                market.home_probability,
                market.draw_probability,
                market.away_probability,

                margin=0.022,
                variance=0.025,

                bookmaker="BetKanyon"

            )

            fixtures.append({

                "match": {

                    "matchId": market.id,

                    "host": self._team_name(market.home_team),

                    "guest": self._team_name(market.away_team),

                    "start": int(market.start_time.timestamp() * 1000)

                },

                "tournament": self._league_name(market.competition),

                "odds": {

                    "1": home_price,
                    "X": draw_price,
                    "2": away_price

                }

            })

        self.export_json({

            "fixtures": fixtures

        })

    def _league_name(self, league):

        mapping = {

            "Premier League": "England EPL",
            "La Liga": "Spain LaLiga",
            "Turkish Super Lig": "Turkey Süper Lig"

        }

        return mapping.get(league, league)

    def _team_name(self, team):

        mapping = {

            "Liverpool": "Liverpool AFC",
            "Chelsea": "Chelsea FC",
            "Arsenal": "Arsenal London",
            "Tottenham": "Spurs",
            "Barcelona": "Barça",
            "Real Madrid": "Real Madrid CF",
            "Galatasaray": "Galatasaray SK",
            "Fenerbahce": "Fenerbahçe SK"

        }

        return mapping.get(team, team)