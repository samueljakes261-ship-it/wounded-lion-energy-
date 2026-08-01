from dataclasses import dataclass


@dataclass
class RunnerOdds:

    selection_id: int

    back: list

    lay: list

    traded_volume: float


@dataclass
class MarketOdds:

    # websocket

    market_id: str

    event_id: str

    market_status: str

    in_play: bool

    runners: list

    # REST catalogue

    home_team: str

    away_team: str

    competition: str

    sport: str

    market_name: str

    start_time: int

    total_matched: float