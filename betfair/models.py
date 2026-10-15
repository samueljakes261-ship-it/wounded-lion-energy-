"""Normalized Betfair valuebets opportunity. Source values are authoritative."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from betfair.config import SOURCE_ID, SOURCE_LABEL

LIVE = "LIVE"
PREMATCH = "PREMATCH"
UNKNOWN = "UNKNOWN"


@dataclass
class BetfairRef:
    bookmaker: str
    value: Optional[float] = None


@dataclass
class BetfairOpportunity:
    source: str = SOURCE_ID
    source_label: str = SOURCE_LABEL
    cluster_id: str = ""
    match_cluster_id: str = ""
    home_team: str = ""
    away_team: str = ""
    start_time: Optional[datetime] = None
    sport: str = ""
    league: str = ""
    market_label: str = ""
    category: Optional[str] = None
    category_label: Optional[str] = None
    direction: str = ""
    iddaa_odd: Optional[float] = None
    ref_odd: Optional[float] = None
    ref_bookmaker: str = ""
    best_back_bookmaker: str = ""
    back_stake: Optional[float] = None
    lay_stake: Optional[float] = None
    lay_liability: Optional[float] = None
    commission_rate: Optional[float] = None
    profit_if_back_wins: Optional[float] = None
    profit_if_back_loses: Optional[float] = None
    guaranteed_profit: Optional[float] = None
    event_orientation: Optional[str] = None
    lay_available_size: Optional[float] = None
    execution_grade: Optional[str] = None
    refs: list[BetfairRef] = field(default_factory=list)
    value_pct: Optional[float] = None
    status: str = ""
    event_match_score: Optional[float] = None
    period: Optional[str] = None
    line: Optional[float] = None
    outcome: str = ""
    is_live: Optional[bool] = None
    live_classification: str = UNKNOWN
    live_clock: Optional[str] = None
    detected_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        if self.cluster_id:
            return self.cluster_id
        line = "" if self.line is None else str(self.line)
        return "|".join(
            (
                self.match_cluster_id,
                self.market_label,
                self.outcome,
                self.direction,
                line,
            )
        )
