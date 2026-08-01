from dataclasses import dataclass

from models.best_odds import BestOdds


@dataclass
class ArbitrageResult:
    """
    Represents the outcome of an arbitrage calculation.
    """

    best_odds: BestOdds

    implied_probability: float

    arbitrage_exists: bool

    profit_percentage: float