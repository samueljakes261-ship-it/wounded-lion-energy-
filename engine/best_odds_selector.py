from debug import odds_trace
from models.best_odds import BestOdds
from models.matched_event import MatchedEvent


class NoBackableOddsError(ValueError):
    """
    Raised when an event has no ordinary fixed-odds (BACK-or-plain)
    price for at least one outcome -- e.g. an event only seen via an
    Orbit LAY quote. Callers should treat this as "skip this event",
    not as a bug.
    """


class BestOddsSelector:
    """
    Finds the highest odds for each outcome.

    A LAY price (side="LAY") is an exchange liability quote, not an
    ordinary fixed-odds bookmaker price -- max(odds) across bookmakers
    is only a valid "best price" comparison for BACK-style prices
    (side is None for OnWin/BetKanyon, or explicitly "BACK" for
    Orbit). LAY prices are therefore excluded here rather than
    silently compared against BACK prices as if they meant the same
    thing (see models/match.py and engine/back_lay_detector.py, which
    handles LAY prices with their own correct math instead).
    """

    def select(self, event: MatchedEvent) -> BestOdds:

        backable = [
            match
            for match in event.matches
            if match.side != "LAY"
        ]

        if not backable:
            raise NoBackableOddsError(
                f"No backable (non-LAY) odds available for "
                f"{event.home_team} vs {event.away_team}."
            )

        home_match = max(
            backable,
            key=lambda match: match.home_odds
        )

        draw_match = max(
            backable,
            key=lambda match: match.draw_odds
        )

        away_match = max(
            backable,
            key=lambda match: match.away_odds
        )

        best = BestOdds(
            home_match=home_match,
            draw_match=draw_match,
            away_match=away_match,
        )

        odds_trace.record_engine_selection(event, best)

        return best