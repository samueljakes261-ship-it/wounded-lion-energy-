"""
Kenyan arbitrage engine.

Reuses the EXISTING, UNMODIFIED engine/* pipeline (MatchFinder ->
BestOddsSelector -> ArbitrageDetector -> StakeCalculator) by feeding it
`KenyanMatchOdds` objects, which are duck-type compatible with
`models.match.MatchOdds` (see kenyan/models.py's docstring for the
verification that none of those classes ever perform an `isinstance`
check). Zero lines of engine/* were changed to make this work.

BACK-vs-BACK only: KenyanMatchOdds never carries a LAY leg, so nothing
extra is needed here to keep this Kenyan-only matcher from ever
producing a BACK-vs-LAY combination.
"""
from typing import List

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector
from engine.match_finder import MatchFinder
from engine.stake_calculator import StakeCalculator
from kenyan.config import KENYAN_BANKROLL
from kenyan.models import KenyanMatchOdds
from models.arbitrage_opportunity import ArbitrageOpportunity

# A "matched event" with only one bookmaker's odds cannot be an
# arbitrage across bookmakers by definition -- MatchFinder still
# returns it as a group of size 1, so this module filters it out
# before running the (comparatively more expensive) detector/
# calculator steps.
MIN_BOOKMAKERS_FOR_ARBITRAGE = 2


class KenyanArbitrageEngine:
    def __init__(self):
        self._finder = MatchFinder()
        self._selector = BestOddsSelector()
        self._detector = ArbitrageDetector()
        self._calculator = StakeCalculator()

    def compute_opportunities(
        self,
        matches: List[KenyanMatchOdds],
        *,
        bankroll: float = KENYAN_BANKROLL,
    ) -> List[ArbitrageOpportunity]:
        if not matches:
            return []

        matched_events = self._finder.find(matches)

        opportunities = []

        for event in matched_events:
            distinct_bookmakers = {match.bookmaker for match in event.matches}
            if len(distinct_bookmakers) < MIN_BOOKMAKERS_FOR_ARBITRAGE:
                continue

            best = self._selector.select(event)
            result = self._detector.detect(best)

            if not result.arbitrage_exists:
                continue

            stake_plan = self._calculator.calculate(result=result, bankroll=bankroll)

            opportunities.append(
                ArbitrageOpportunity(event=event, result=result, stake_plan=stake_plan)
            )

        return opportunities
