from datetime import datetime

from engine.arbitrage_detector import ArbitrageDetector
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

# Orbit
event.add_match(
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
    )
)

# Betfair
event.add_match(
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
    )
)

selector = BestOddsSelector()
best = selector.select(event)

detector = ArbitrageDetector()

result = detector.detect(best)

print("\n" + "=" * 60)
print("           ARBITRAGE DETECTION RESULT")
print("=" * 60)

print(f"\nEvent       : {event.home_team} vs {event.away_team}")
print(f"Competition : {event.competition}")
print(f"Sport       : {event.sport}")
print(f"Market      : {event.market}")

print("\n" + "-" * 60)
print("BEST HOME BET")
print("-" * 60)
print(f"Bookmaker : {best.home_match.bookmaker}")
print(f"Odds      : {best.home_match.home_odds}")

print("\n" + "-" * 60)
print("BEST DRAW BET")
print("-" * 60)
print(f"Bookmaker : {best.draw_match.bookmaker}")
print(f"Odds      : {best.draw_match.draw_odds}")

print("\n" + "-" * 60)
print("BEST AWAY BET")
print("-" * 60)
print(f"Bookmaker : {best.away_match.bookmaker}")
print(f"Odds      : {best.away_match.away_odds}")

print("\n" + "=" * 60)
print("ARBITRAGE SUMMARY")
print("=" * 60)

print(f"Implied Probability : {result.implied_probability:.4f}")
print(f"Arbitrage Exists    : {result.arbitrage_exists}")
print(f"Profit Percentage   : {result.profit_percentage:.2f}%")

print("=" * 60)