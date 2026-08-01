from models.best_odds import BestOdds
from models.matched_event import MatchedEvent


class BestOddsSelector:
    """
    Finds the highest odds for each outcome.
    """

    def select(self, event: MatchedEvent) -> BestOdds:

        home_match = max(
            event.matches,
            key=lambda match: match.home_odds
        )

        draw_match = max(
            event.matches,
            key=lambda match: match.draw_odds
        )

        away_match = max(
            event.matches,
            key=lambda match: match.away_odds
        )

        return BestOdds(
            home_match=home_match,
            draw_match=draw_match,
            away_match=away_match,
        )