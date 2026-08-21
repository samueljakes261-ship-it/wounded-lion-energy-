"""Prematch-only event matcher.

The live EventMatcher uses a 3-letter first-word prefix. That collides
Arabic 'Al … vs Al …' fixtures and was observed to attach Orbit BACK
prices from one match onto a different BetKanyon event name.

Prematch matching requires the fully normalized home and away names
to be equal. Live EventMatcher is not imported or modified.
"""

from engine.normalizer import TeamNameNormalizer
from models.match import MatchOdds
from models.matched_event import MatchedEvent


class PrematchEventMatcher:
    def __init__(self):
        self.normalizer = TeamNameNormalizer()

    def _key(self, team: str) -> str:
        return self.normalizer.normalize(team or "").strip().lower()

    def _sport(self, match: MatchOdds) -> str:
        sport = (match.sport or "").lower()
        if sport == "soccer":
            return "football"
        return sport

    def is_same_event(self, match1: MatchOdds, match2: MatchOdds) -> bool:
        feed1 = getattr(match1, "feed_type", "live") or "live"
        feed2 = getattr(match2, "feed_type", "live") or "live"
        if feed1 != feed2:
            return False
        if feed1 != "prematch":
            return False
        if self._sport(match1) != self._sport(match2):
            return False
        home1 = self._key(match1.home_team)
        away1 = self._key(match1.away_team)
        home2 = self._key(match2.home_team)
        away2 = self._key(match2.away_team)
        if not home1 or not away1 or not home2 or not away2:
            return False
        return home1 == home2 and away1 == away2


class PrematchMatchFinder:
    def __init__(self):
        self.matcher = PrematchEventMatcher()

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
                if match.bookmaker == other.bookmaker:
                    continue
                if self.matcher.is_same_event(match, other):
                    event.add_match(other)
                    used.add(j)
            matched_events.append(event)
        return matched_events
