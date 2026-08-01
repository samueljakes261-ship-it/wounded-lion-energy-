from dataclasses import dataclass

from models.matched_event import MatchedEvent
from models.arbitrage_result import ArbitrageResult
from models.stake_plan import StakePlan


@dataclass
class ArbitrageOpportunity:
    """
    Represents one complete arbitrage opportunity.
    This is the object that will eventually be shown
    in the UI or exported to CSV.
    """

    event: MatchedEvent

    result: ArbitrageResult

    stake_plan: StakePlan