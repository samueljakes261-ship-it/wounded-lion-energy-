from datetime import datetime

from engine.best_odds_selector import BestOddsSelector
from models.match import MatchOdds
from models.matched_event import MatchedEvent

event = MatchedEvent(
    sport="Football",
    competition="Premier League",
    home_team="Liverpool",
    away_team="Chelsea",
    market="1X2",
)

event.add_match(
    MatchOdds(
        bookmaker="Orbit",
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team="Liverpool",
        away_team="Chelsea",
        home_odds=2.15,
        draw_odds=3.40,
        away_odds=3.60,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    )
)

event.add_match(
    MatchOdds(
        bookmaker="Betfair",
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team="Liverpool FC",
        away_team="Chelsea FC",
        home_odds=2.20,
        draw_odds=3.45,
        away_odds=3.55,
        start_time=datetime.now(),
        collected_at=datetime.now(),
    )
)

selector = BestOddsSelector()

best = selector.select(event)

print("\n===== BEST ODDS =====\n")

print(
    f"HOME : {best.home_odds} ({best.home_match.bookmaker})"
)

print(
    f"DRAW : {best.draw_odds} ({best.draw_match.bookmaker})"
)

print(
    f"AWAY : {best.away_odds} ({best.away_match.bookmaker})"
)