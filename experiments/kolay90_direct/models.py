"""Experiment-local MatchOdds. Does not modify models.match."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExperimentMatchOdds:
    bookmaker: str
    event_id: str
    home_team: str
    away_team: str
    start_time: datetime
    feed_type: str
    sport: str
    home_back: float
    draw_back: float
    away_back: float
    collected_at: datetime
    competition: str | None = None
    raw_home: str | None = None
    raw_draw: str | None = None
    raw_away: str | None = None
