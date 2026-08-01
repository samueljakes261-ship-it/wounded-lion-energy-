from dataclasses import dataclass

from models.bet_instruction import BetInstruction


@dataclass
class StakePlan:
    """
    Complete betting plan for one arbitrage.
    """

    home: BetInstruction

    draw: BetInstruction

    away: BetInstruction

    total_stake: float

    guaranteed_return: float

    guaranteed_profit: float

    roi: float