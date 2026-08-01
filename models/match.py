from dataclasses import dataclass
from datetime import datetime


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

    def __str__(self):
        return (
            f"\nBookmaker : {self.bookmaker}\n"
            f"Competition : {self.competition}\n"
            f"Sport : {self.sport}\n"
            f"Market : {self.market}\n"
            f"Match : {self.home_team} vs {self.away_team}\n"
            f"Odds : {self.home_odds} | {self.draw_odds} | {self.away_odds}\n"
            f"Start : {self.start_time}\n"
            f"Collected : {self.collected_at}"
        )