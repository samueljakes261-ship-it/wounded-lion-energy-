from datetime import datetime

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector
from engine.stake_calculator import StakeCalculator

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
        home_odds=2.30,
        draw_odds=3.50,
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

calculator = StakeCalculator()

plan = calculator.calculate(
    result=result,
    bankroll=1000,
)

print("\n" + "=" * 65)
print("                 STAKE PLAN")
print("=" * 65)

for bet in [plan.home, plan.draw, plan.away]:

    print(f"\nOutcome    : {bet.outcome}")
    print(f"Bookmaker  : {bet.bookmaker}")
    print(f"Odds       : {bet.odds}")
    print(f"Stake      : ${bet.stake}")

print("\n" + "=" * 65)

print(f"Total Stake        : ${plan.total_stake}")
print(f"Guaranteed Return  : ${plan.guaranteed_return}")
print(f"Guaranteed Profit  : ${plan.guaranteed_profit}")
print(f"ROI                : {plan.roi}%")

print("=" * 65)