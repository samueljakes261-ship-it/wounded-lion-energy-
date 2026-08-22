from dataclasses import dataclass


OPPORTUNITY_TYPE_BACK_BACK = "BACK_BACK"
OPPORTUNITY_TYPE_BACK_LAY = "BACK_LAY"


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

    # Kept for the live BackLayDetector's internal stake-split math.
    # BACK-vs-LAY API cards must not expose this (or any other
    # calculation). Default 0: the prematch detector does not compute
    # it -- there is no exchange-commission configuration in this
    # project, so profitability is the raw BACK > LAY test.
    profit_percentage: float = 0.0

    opportunity_type: str = OPPORTUNITY_TYPE_BACK_LAY
    feed_type: str = "live"
    market: str = ""
    back_side: str = "BACK"
    lay_side: str = "LAY"

    def arbitrage_team(self) -> str:
        if self.outcome == "HOME":
            return self.home_team
        if self.outcome == "AWAY":
            return self.away_team
        return ""

    def to_api_dict(self) -> dict:
        """UI payload: match, team, explicit BACK/LAY prices only."""
        return {
            "opportunityType": OPPORTUNITY_TYPE_BACK_LAY,
            "sport": self.sport,
            "competition": self.competition,
            "market": self.market,
            "feedType": self.feed_type,
            "homeTeam": self.home_team,
            "awayTeam": self.away_team,
            "outcome": self.outcome,
            "arbitrageTeam": self.arbitrage_team(),
            "back": {
                "bookmaker": self.back_bookmaker,
                "side": self.back_side or "BACK",
                "odds": self.back_odds,
            },
            "lay": {
                "bookmaker": self.lay_bookmaker,
                "side": self.lay_side or "LAY",
                "odds": self.lay_odds,
            },
        }
