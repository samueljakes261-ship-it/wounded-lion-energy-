from dataclasses import dataclass

from models.matched_event import MatchedEvent
from models.arbitrage_result import ArbitrageResult


@dataclass
class Opportunity:

    event: MatchedEvent

    result: ArbitrageResult