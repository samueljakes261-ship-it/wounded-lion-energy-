from dataclasses import dataclass


@dataclass
class BackLayOpportunity:
    """
    A guaranteed-profit hedge from backing one outcome at a fixed-odds
    price and laying the SAME outcome on an exchange (Orbit) at a
    lower price -- a fundamentally different bet structure from the
    3-way ArbitrageResult (see engine/arbitrage_detector.py), which
    assumes every leg is a fixed-odds BACK bet across three different
    outcomes. This is two legs on ONE outcome instead.
    """

    outcome: str  # "HOME" | "DRAW" | "AWAY"

    sport: str
    competition: str
    home_team: str
    away_team: str

    back_bookmaker: str
    back_odds: float

    lay_bookmaker: str
    lay_odds: float

    # Guaranteed profit as a percentage of total stake across both
    # legs, using the stake split that equalizes profit in both
    # outcomes (see engine/back_lay_detector.py for the derivation).
    profit_percentage: float
