from datetime import datetime

from engine.matcher import EventMatcher
from models.match import MatchOdds

matcher = EventMatcher()

match1 = MatchOdds(
    bookmaker="Orbit",
    competition="Premier League",
    sport="Football",
    market="1X2",
    home_team="Liverpool",
    away_team="Chelsea",
    home_odds=2.10,
    draw_odds=3.30,
    away_odds=3.60,
    start_time=datetime.now(),
    collected_at=datetime.now()
)

match2 = MatchOdds(
    bookmaker="Betfair",
    competition="Premier League",
    sport="Football",
    market="1X2",
    home_team="Liverpool FC",
    away_team="Chelsea FC",
    home_odds=2.20,
    draw_odds=3.40,
    away_odds=3.70,
    start_time=datetime.now(),
    collected_at=datetime.now()
)

print("Should be TRUE:")
print(matcher.is_same_event(match1, match2))