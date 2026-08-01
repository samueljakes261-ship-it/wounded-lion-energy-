from engine.matcher import EventMatcher

from models.match import MatchOdds
from models.matched_event import MatchedEvent


class MatchFinder:
    """
    Groups MatchOdds that represent the same sporting event,
    regardless of bookmaker.
    """

    def __init__(self):

        self.matcher = EventMatcher()

    def find(self, matches: list[MatchOdds]) -> list[MatchedEvent]:

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

                if self.matcher.is_same_event(match, other):

                    event.add_match(other)
                    used.add(j)

            matched_events.append(event)

        return matched_events