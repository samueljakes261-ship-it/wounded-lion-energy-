from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class MatchOdds:
    """
    Represents one betting market from one bookmaker.
    """

    bookmaker: str
    competition: str
    sport: str
    market: str

    home_team: str
    away_team: str

    home_odds: float
    draw_odds: float
    away_odds: float

    start_time: datetime
    collected_at: datetime

    # Exchange semantics (Orbit, etc.). None means "ordinary fixed-odds
    # bookmaker" (OnWin, BetKanyon) -- there is no BACK/LAY distinction
    # for those, so this field is simply absent/None for them. Exchange
    # sources MUST set this to "BACK" or "LAY" explicitly; a LAY price
    # is NOT a normal bookmaker price and must never be treated as one
    # (see engine/best_odds_selector.py and engine/back_lay_detector.py).
    side: Optional[str] = None

    # live | prematch -- default "live" so existing adapters are
    # unchanged. Prematch feeds set this explicitly so a live event
    # and a prematch event with the same team names can never collapse
    # into one opportunity.
    feed_type: str = "live"

    # BetKanyon prematch tournament/competition id this event came
    # from. Unused (None) for live feeds and for Orbit.
    tournament_id: Optional[str] = None

    def __str__(self):
        side_label = f" [{self.side}]" if self.side else ""
        return (
            f"\nBookmaker : {self.bookmaker}{side_label}\n"
            f"Competition : {self.competition}\n"
            f"Sport : {self.sport}\n"
            f"Market : {self.market}\n"
            f"Match : {self.home_team} vs {self.away_team}\n"
            f"Odds : {self.home_odds} | {self.draw_odds} | {self.away_odds}\n"
            f"Start : {self.start_time}\n"
            f"Collected : {self.collected_at}"
        )