from engine.match_finder import MatchFinder
from engine.best_odds_selector import BestOddsSelector
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator

from models.arbitrage_opportunity import ArbitrageOpportunity


class ScannerService:
    """
    Coordinates the complete arbitrage scanning pipeline.
    """

    def __init__(self):

        self.match_finder = MatchFinder()
        self.best_selector = BestOddsSelector()
        self.detector = ArbitrageDetector()
        self.calculator = StakeCalculator()

    def scan(self, matches, bankroll):

        opportunities = []

        print()
        print("=" * 70)
        print("SCANNER DEBUG")
        print("=" * 70)
        print()

        print(f"Incoming MatchOdds : {len(matches)}")

        matched_events = self.match_finder.find(matches)

        print(f"Matched Events : {len(matched_events)}")
        print()

        for index, event in enumerate(matched_events, start=1):

            print("-" * 70)
            print(
                f"EVENT {index}: "
                f"{event.home_team} vs {event.away_team}"
            )
            print(
                f"Competition : {event.competition}"
            )
            print(f"Bookmakers : {len(event.matches)}")

            for match in event.matches:

                print(
                    f"   {match.bookmaker:<15}"
                    f"{match.home_team} vs {match.away_team}"
                )

            best = self.best_selector.select(event)

            result = self.detector.detect(best)

            print(
                f"Arbitrage : {result.arbitrage_exists}"
            )

            print(
                f"Implied Probability : "
                f"{result.implied_probability:.4f}"
            )

            if not result.arbitrage_exists:
                continue

            plan = self.calculator.calculate(
                result=result,
                bankroll=bankroll
            )

            opportunity = ArbitrageOpportunity(
                event=event,
                result=result,
                stake_plan=plan
            )

            opportunities.append(opportunity)

        print()
        print("=" * 70)
        print(f"TOTAL OPPORTUNITIES : {len(opportunities)}")
        print("=" * 70)
        print()

        return opportunities