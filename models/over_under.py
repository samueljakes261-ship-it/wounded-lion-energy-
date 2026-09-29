"""Two-way Over/Under opportunity, separate from 3-way 1X2."""

from dataclasses import dataclass

from models.matched_event import MatchedEvent
from models.match import MatchOdds

OPPORTUNITY_TYPE_OVER_UNDER = "OVER_UNDER"


@dataclass
class TwoWayBestOdds:
    over_match: MatchOdds
    under_match: MatchOdds

    @property
    def over_odds(self) -> float:
        return self.over_match.home_odds

    @property
    def under_odds(self) -> float:
        return self.under_match.away_odds


@dataclass
class OverUnderOpportunity:
    event: MatchedEvent
    best: TwoWayBestOdds
    line: float
    implied_probability: float
    profit_percentage: float
    over_stake: float
    under_stake: float
    total_stake: float
    guaranteed_return: float
    guaranteed_profit: float
    roi: float
    feed_type: str = "prematch"

    def to_api_dict(self, generated_at=None) -> dict:
        event = self.event
        over = self.best.over_match
        under = self.best.under_match
        return {
            "opportunityType": OPPORTUNITY_TYPE_OVER_UNDER,
            "sport": event.sport,
            "competition": event.competition,
            "market": "over_under",
            "line": self.line,
            "homeTeam": event.home_team,
            "awayTeam": event.away_team,
            "feedType": self.feed_type,
            "profitPercentage": round(self.profit_percentage, 2),
            "impliedProbability": round(self.implied_probability, 4),
            "roi": round(self.roi, 2),
            "guaranteedProfit": round(self.guaranteed_profit, 2),
            "guaranteedReturn": round(self.guaranteed_return, 2),
            "totalStake": round(self.total_stake, 2),
            "generatedAt": generated_at,
            "over": {
                "bookmaker": over.bookmaker,
                "odds": over.home_odds,
                "stake": self.over_stake,
                "side": over.side,
                "market": over.market,
                "selection": "over",
            },
            "under": {
                "bookmaker": under.bookmaker,
                "odds": under.away_odds,
                "stake": self.under_stake,
                "side": under.side,
                "market": under.market,
                "selection": "under",
            },
        }
