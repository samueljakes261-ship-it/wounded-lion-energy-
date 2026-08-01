from dataclasses import dataclass

from models.match import MatchOdds


@dataclass
class BestOdds:
    """
    Stores the best available odds for a matched event.
    """

    home_match: MatchOdds
    draw_match: MatchOdds
    away_match: MatchOdds

    @property
    def home_odds(self):
        return self.home_match.home_odds

    @property
    def draw_odds(self):
        return self.draw_match.draw_odds

    @property
    def away_odds(self):
        return self.away_match.away_odds