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

    # Same closed-form as engine/back_lay_detector.py:
    # (BACK - LAY) / (BACK + LAY) * 100. Detection stays BACK > LAY;
    # this field is only exposed as profitPercentage on the card.
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
        """UI payload: match, team, BACK/LAY prices, and existing %."""
        pct = self.profit_percentage
        if not pct and self.back_odds and self.lay_odds:
            pct = (
                (self.back_odds - self.lay_odds)
                / (self.back_odds + self.lay_odds)
                * 100
            )
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
            "profitPercentage": round(pct, 2),
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
