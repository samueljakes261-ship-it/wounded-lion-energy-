from dataclasses import dataclass


@dataclass
class RunnerOdds:

    selection_id: int

    # Ladders of {"index": int, "odds": float, "amount": float}, index 0
    # is Orbit's own explicit "best price" marker for that side (see
    # parsers/orbit/parser.py and parsers/orbit/adapter.py for why this
    # -- rather than the "catb"/"catl" arrays -- is the field actually
    # used for top-of-book price).
    back: list

    lay: list

    traded_volume: float

    # Catalogue runner name (e.g. "Liverpool", "The Draw"). None for
    # runners built from a websocket frame alone, before being merged
    # with catalogue data in OrbitParser.parse(). Used by OrbitAdapter
    # to identify home/draw/away by NAME rather than by array position,
    # since Orbit's runner order is not guaranteed to be [home, draw,
    # away] (see adapter.py).
    name: str = None


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