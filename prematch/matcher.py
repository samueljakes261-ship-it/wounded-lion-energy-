"""Prematch-only event matcher.

Live EventMatcher uses a 3-letter first-word prefix and is not imported
or modified. Prematch matching is conservative and cross-book only:

After TeamNameNormalizer, two bookmakers' events match when the first
two characters of the home names agree AND the first two characters of
the away names agree. Short leading particles (Al, CD, ...) are skipped
so "Al Ittihad Kalba vs Al Wasl" does not collide with "Al Ain vs Al
Jazira". Crowded 2-char buckets only merge 1:1, so Manchester United vs
Chelsea is not glued onto Manchester City vs Chelsea.
"""

from collections import defaultdict

from engine.normalizer import TeamNameNormalizer
from models.match import MatchOdds
from models.matched_event import MatchedEvent


PREFIX_LEN = 2


class PrematchEventMatcher:
    def __init__(self):
        self.normalizer = TeamNameNormalizer()

    def _key(self, team: str) -> str:
        return self.normalizer.normalize(team or "").strip().lower()

    def _significant_words(self, key: str) -> list:
        words = [word for word in (key or "").split() if word]
        while words and len(words[0]) < PREFIX_LEN:
            words.pop(0)
        if words and len(words[0]) <= PREFIX_LEN and len(words) >= 2:
            # "al ittihad" / "cd olimpia": first 2 chars come from the
            # distinctive token, not the particle.
            return words[1:]
        return words

    def _prefix(self, key: str) -> str:
        words = self._significant_words(key)
        if not words:
            compact = (key or "").replace(" ", "")
            return compact[:PREFIX_LEN] if len(compact) >= PREFIX_LEN else ""
        token = words[0]
        return token[:PREFIX_LEN] if len(token) >= PREFIX_LEN else ""

    def _side_compat(self, key1: str, key2: str) -> bool:
        if not key1 or not key2:
            return False
        if key1 == key2:
            return True
        prefix1 = self._prefix(key1)
        prefix2 = self._prefix(key2)
        if len(prefix1) < PREFIX_LEN or prefix1 != prefix2:
            return False
        words1 = self._significant_words(key1)
        words2 = self._significant_words(key2)
        if not words1 or not words2:
            return False
        for left, right in zip(words1, words2):
            if left[:PREFIX_LEN] != right[:PREFIX_LEN]:
                return False
            shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
            if not longer.startswith(shorter):
                return False
        return True

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
        return self._side_compat(home1, home2) and self._side_compat(away1, away2)


class PrematchMatchFinder:
    def __init__(self):
        self.matcher = PrematchEventMatcher()

    def _event_from_group(self, group):
        first = group[0]
        event = MatchedEvent(
            sport=first.sport,
            competition=first.competition,
            home_team=first.home_team,
            away_team=first.away_team,
            market=first.market,
        )
        for item in group:
            event.add_match(item)
        return event

    def find(self, matches: list[MatchOdds]) -> list[MatchedEvent]:
        buckets = {}
        unmatched = []
        for match in matches:
            feed = getattr(match, "feed_type", "prematch") or "prematch"
            home = self.matcher._key(match.home_team)
            away = self.matcher._key(match.away_team)
            sport = self.matcher._sport(match)
            if feed != "prematch" or not home or not away:
                unmatched.append(match)
                continue
            buckets.setdefault((feed, sport, home, away), []).append(match)

        clusters = []
        for key, group in buckets.items():
            books = {item.bookmaker.lower() for item in group}
            clusters.append((key, group, books))

        parent = list(range(len(clusters)))

        def find_parent(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            root_left = find_parent(left)
            root_right = find_parent(right)
            if root_left != root_right:
                parent[root_right] = root_left

        by_prefix = defaultdict(list)
        for index, (key, _group, _books) in enumerate(clusters):
            feed, sport, home, away = key
            by_prefix[
                (feed, sport, self.matcher._prefix(home), self.matcher._prefix(away))
            ].append(index)

        for indexes in by_prefix.values():
            compatible = {index: [] for index in indexes}
            for left in indexes:
                for right in indexes:
                    if left >= right:
                        continue
                    key_left, _group_left, books_left = clusters[left]
                    key_right, _group_right, books_right = clusters[right]
                    if books_left & books_right:
                        continue
                    if self.matcher._side_compat(key_left[2], key_right[2]) and self.matcher._side_compat(
                        key_left[3], key_right[3]
                    ):
                        compatible[left].append(right)
                        compatible[right].append(left)
            for index in indexes:
                partners = compatible[index]
                if len(partners) != 1:
                    continue
                other = partners[0]
                if len(compatible[other]) != 1:
                    continue
                union(index, other)

        merged = defaultdict(list)
        for index, (_key, group, _books) in enumerate(clusters):
            merged[find_parent(index)].extend(group)

        matched_events = [self._event_from_group(group) for group in merged.values()]
        for match in unmatched:
            matched_events.append(self._event_from_group([match]))
        return matched_events
