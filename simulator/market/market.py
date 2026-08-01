from dataclasses import dataclass
from datetime import datetime


@dataclass
class Market:

    id: str

    sport: str

    competition: str

    home_team: str

    away_team: str

    start_time: datetime

    home_probability: float

    draw_probability: float

    away_probability: float