"""
Normalized data model for the Kenyan Bookmakers module.

IMPORTANT DESIGN NOTE -- why this duck-types models.match.MatchOdds
--------------------------------------------------------------------
`KenyanMatchOdds` intentionally exposes the exact same attribute names
as the existing `models.match.MatchOdds` (bookmaker, competition,
sport, market, home_team, away_team, home_odds, draw_odds, away_odds,
start_time, collected_at). None of engine/matcher.py,
engine/match_finder.py, engine/normalizer.py,
engine/best_odds_selector.py, engine/arbitrage_detector.py or
engine/stake_calculator.py perform an `isinstance(...)` check anywhere
-- they only ever read these attributes by name (verified by
inspection before writing this module). That means this isolated
Kenyan module can reuse the EXISTING, UNMODIFIED BestOddsSelector /
ArbitrageDetector / StakeCalculator for BACK-vs-BACK math. Event
identity uses kenyan.matcher.KenyanMatchFinder instead of the
Turkish live 3-character EventMatcher.

Extra fields (`event_id`, `cluster_id`, `market_id`, `status`,
`source`, team/league ids) are Kenyan-specific provenance. The shared
BestOddsSelector / ArbitrageDetector never read them; the Kenyan
matcher and engine validation layer do.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class KenyanMatchOdds:
    """
    One BACK-only 1X2 market from one Kenyan bookmaker.

    `side` always stays None: the Kenyan module is BACK-vs-BACK only
    (no exchange, no LAY leg), by design. The field itself still has
    to exist because `engine/best_odds_selector.py` and
    `debug/odds_trace.py` read `match.side` unconditionally (they were
    extended, on top of the branch this module was merged into, to
    support Orbit's BACK/LAY exchange semantics) -- `side=None` reads
    there as "an ordinary backable price", which is exactly what every
    Kenyan bookmaker price is. This is duck-typing the CURRENT shape of
    `models.match.MatchOdds` on whichever branch this lands on, not a
    reintroduction of LAY support: nothing in this module ever sets
    `side` to anything other than its default.
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

    # Kenyan-specific provenance. event_id is the bookmaker's own
    # fixture id (not shared across books). cluster_id / market_id
    # keep 1xBet/22Bet 1X2 selections inside the cluster they came from.
    event_id: str = ""
    cluster_id: str = ""
    market_id: str = ""
    parent_event_id: str = ""
    home_team_id: str = ""
    away_team_id: str = ""
    league_id: str = ""
    status: str = "PREMATCH"  # "LIVE" or "PREMATCH" -- see kenyan/config.py
    source: str = ""  # e.g. "sportpesa_live", "betika_prematch"

    # Duck-typed to match models.match.MatchOdds's own fields (see the
    # class docstring above) -- always None/live-derived for Kenyan.
    side: Optional[str] = None
    tournament_id: Optional[str] = None
    line: Optional[float] = None

    @property
    def feed_type(self) -> str:
        """
        Read by engine/matcher.py (`getattr(match, "feed_type", "live")`)
        to keep LIVE and PREMATCH events from ever matching each other.
        Derived from `status` rather than stored separately so it is
        never possible for the two to disagree.
        """
        return "live" if self.status == "LIVE" else "prematch"

    def __str__(self):
        return (
            f"\n[{self.status}] Bookmaker : {self.bookmaker}\n"
            f"Competition : {self.competition}\n"
            f"Sport : {self.sport}\n"
            f"Market : {self.market}\n"
            f"Match : {self.home_team} vs {self.away_team}\n"
            f"Odds : {self.home_odds} | {self.draw_odds} | {self.away_odds}\n"
            f"Start : {self.start_time}\n"
            f"Collected : {self.collected_at}\n"
            f"Source : {self.source}"
        )
