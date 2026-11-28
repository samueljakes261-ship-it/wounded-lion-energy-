from engine.matcher import EventMatcher

from models.match import MatchOdds
from models.markets import arb_group_key
from models.matched_event import MatchedEvent


def quotes_for_cross_book_groups(matches):
    """Drop LAY quotes before KenyanMatchFinder groups a fixture.

    KenyanMatchFinder treats two listings from one bookmaker as ambiguous
    and drops the fixture. Orbit publishes a BACK quote and a LAY quote
    for the same event. The LAY quote stays available to the BACK-vs-LAY
    detector, which compares it one pair at a time.
    """
    grouped = []
    for match in matches:
        side = getattr(match, "side", None)
        if side is not None and str(side).strip().upper() == "LAY":
            continue
        grouped.append(match)
    return grouped


class MatchFinder:
    """
    Groups MatchOdds that represent the same sporting event
    across different bookmakers.
    """

    def __init__(self):

        self.matcher = EventMatcher()

    def find(
        self,
        matches: list[MatchOdds],
    ) -> list[MatchedEvent]:

        matched_events = []

        used = set()

        for i, match in enumerate(matches):

            if i in used:
                continue

            event = MatchedEvent(
                sport=match.sport,
                competition=match.competition,
                home_team=match.home_team,
                away_team=match.away_team,
                market=match.market,
            )

            event.add_match(match)
            used.add(i)

            for j in range(i + 1, len(matches)):

                if j in used:
                    continue

                other = matches[j]

                #
                # Never match two odds from the
                # same bookmaker.
                #

                if match.bookmaker == other.bookmaker:
                    continue

                # Same teams can carry 1X2 and O/U; arb groups must not mix.
                if arb_group_key(match) != arb_group_key(other):
                    continue

                #
                # Match the sporting event.
                #

                if self.matcher.is_same_event(
                    match,
                    other,
                ):

                    event.add_match(other)
                    used.add(j)

            matched_events.append(event)

        return matched_events