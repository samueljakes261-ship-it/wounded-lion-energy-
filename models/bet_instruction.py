from dataclasses import dataclass


@dataclass
class BetInstruction:
    """
    Represents one bet the user should place.
    """

    outcome: str

    bookmaker: str

    odds: float

    stake: float