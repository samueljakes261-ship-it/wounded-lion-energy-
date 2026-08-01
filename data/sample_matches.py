from datetime import datetime

from models.match import MatchOdds


def load_sample_matches():

    return [

        MatchOdds(
            bookmaker="Orbit",
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Liverpool",
            away_team="Chelsea",
            home_odds=2.30,
            draw_odds=3.50,
            away_odds=3.60,
            start_time=datetime.now(),
            collected_at=datetime.now(),
        ),

        MatchOdds(
            bookmaker="Betfair",
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Liverpool FC",
            away_team="Chelsea FC",
            home_odds=2.40,
            draw_odds=3.60,
            away_odds=3.80,
            start_time=datetime.now(),
            collected_at=datetime.now(),
        ),

    ]