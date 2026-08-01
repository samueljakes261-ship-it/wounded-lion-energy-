from dataclasses import dataclass


@dataclass
class BookmakerConfig:

    name: str

    update_interval_min: int

    update_interval_max: int

    volatility: float


BOOKMAKERS = [

    BookmakerConfig(

        name="Orbit",

        update_interval_min=90,

        update_interval_max=300,

        volatility=0.02,

    ),

    BookmakerConfig(

        name="Betfair",

        update_interval_min=60,

        update_interval_max=180,

        volatility=0.015,

    ),

    BookmakerConfig(

        name="Kolay90",

        update_interval_min=120,

        update_interval_max=360,

        volatility=0.03,

    ),

    BookmakerConfig(

        name="Novel34",

        update_interval_min=90,

        update_interval_max=240,

        volatility=0.025,

    ),

    BookmakerConfig(

        name="BetKanyon",

        update_interval_min=120,

        update_interval_max=300,

        volatility=0.03,

    ),

    BookmakerConfig(

        name="OnWin",

        update_interval_min=120,

        update_interval_max=300,

        volatility=0.025,

    ),

]