from dataclasses import dataclass, field

from models.match import MatchOdds


@dataclass
class MatchedEvent:
    """
    Represents one sporting event that exists
    across multiple bookmakers.
    """

    sport: str
    competition: str
    home_team: str
    away_team: str
    market: str

    matches: list[MatchOdds] = field(default_factory=list)

    def add_match(self, match: MatchOdds):

        self.matches.append(match)