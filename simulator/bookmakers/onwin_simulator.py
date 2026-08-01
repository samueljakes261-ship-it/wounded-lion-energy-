from simulator.base_simulator import BaseSimulator
from simulator.market.market_generator import MarketGenerator
from simulator.market.price_engine import PriceEngine


class OnWinSimulator(BaseSimulator):

    def __init__(self):

        super().__init__("OnWin")

        self.generator = MarketGenerator()
        self.engine = PriceEngine()

    def generate(self):

        games = []

        for market in self.generator.generate():

            home_price, draw_price, away_price = self.engine.generate_prices(

                market.home_probability,
                market.draw_probability,
                market.away_probability,

                margin=0.024,
                variance=0.020,

                bookmaker="OnWin"

            )

            games.append({

                "eventId": market.id,

                "leagueName": self._league_name(
                    market.competition
                ),

                "homeName": self._team_name(
                    market.home_team
                ),

                "awayName": self._team_name(
                    market.away_team
                ),

                "kickoffTime": int(
                    market.start_time.timestamp() * 1000
                ),

                "markets": {

                    "homeWin": home_price,

                    "draw": draw_price,

                    "awayWin": away_price

                }

            })

        self.export_json({

            "games": games

        })

    def _league_name(self, league):

        mapping = {

            "Premier League": "EPL England",

            "La Liga": "LaLiga EA",

            "Turkish Super Lig": "Süper Lig TR"

        }

        return mapping.get(league, league)

    def _team_name(self, team):

        mapping = {

            "Liverpool": "LFC",

            "Chelsea": "CFC",

            "Arsenal": "Arsenal FC",

            "Tottenham": "Tottenham Hotspur",

            "Barcelona": "FCB",

            "Real Madrid": "R. Madrid",

            "Galatasaray": "Gala",

            "Fenerbahce": "Fener"

        }

        return mapping.get(team, team)