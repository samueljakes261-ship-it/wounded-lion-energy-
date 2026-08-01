from datetime import datetime

from models.match import MatchOdds


class OrbitAdapter:

    @staticmethod
    def to_match_odds(market):

        # Only support classic 1-X-2 markets for now
        if len(market.runners) != 3:
            return None

        home = market.runners[0]
        draw = market.runners[1]
        away = market.runners[2]

        if (
            not home.back
            or not draw.back
            or not away.back
        ):
            return None

        return MatchOdds(

            bookmaker="Orbit",

            competition=market.competition,

            sport=market.sport,

            market=market.market_name,

            home_team=market.home_team,

            away_team=market.away_team,

            home_odds=home.back[0][0],

            draw_odds=draw.back[0][0],

            away_odds=away.back[0][0],

            start_time=datetime.fromtimestamp(
                market.start_time / 1000
            ),

            collected_at=datetime.now(),
        )