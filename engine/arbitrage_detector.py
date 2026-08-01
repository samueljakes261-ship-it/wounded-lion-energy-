from models.arbitrage_result import ArbitrageResult
from models.best_odds import BestOdds


class ArbitrageDetector:
    """
    Detects whether a set of best odds
    forms an arbitrage opportunity.
    """

    def detect(self, best_odds: BestOdds) -> ArbitrageResult:

        implied_probability = (

            (1 / best_odds.home_odds)

            + (1 / best_odds.draw_odds)

            + (1 / best_odds.away_odds)

        )

        arbitrage_exists = implied_probability < 1

        profit_percentage = max(
            0,
            (1 - implied_probability) * 100
        )

        return ArbitrageResult(

            best_odds=best_odds,

            implied_probability=implied_probability,

            arbitrage_exists=arbitrage_exists,

            profit_percentage=profit_percentage,

        )