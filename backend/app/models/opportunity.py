from pydantic import BaseModel


class Opportunity(BaseModel):
    id: int
    match: str
    sport: str

    bookmaker_home: str
    bookmaker_draw: str
    bookmaker_away: str

    home_odds: float
    draw_odds: float
    away_odds: float

    profit_percent: float
    status: str