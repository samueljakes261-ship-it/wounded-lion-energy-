"""Kenyan event identity / matching.

Replaces reuse of engine.matcher.EventMatcher (first-3-character
prefixes) for Kenyan bookmakers only. Turkish live EventMatcher and
prematch PrematchEventMatcher are not imported or modified.

Hierarchy, strongest first:

1. Exact canonical team names (TeamNameNormalizer + TEAM_ALIASES)
   plus compatible start time, same sport, same feed, same market.
2. Controlled token fallback (unique 1:1 pairing only).
3. Ambiguous candidates are rejected rather than merged.
4. Weak 3-character prefixes are never sufficient.

Bookmaker event IDs are recorded for provenance and never used to
force two different books together (namespaces differ). League
equality is not required.
"""
from collections import defaultdict
from datetime import timedelta

from engine.normalizer import TeamNameNormalizer
from kenyan.log import event_label, log_matcher, reset_matcher_log_budget
from kenyan.markets import kenyan_market_key
from models.matched_event import MatchedEvent
from resources.aliases import TEAM_ALIASES

START_TIME_TOLERANCE = timedelta(minutes=90)
MIN_FUZZY_TOKEN_LEN = 4
_PARTICLES = frozenset({"and", "the", "de", "la", "el", "of", "at", "vs", "a"})
_IGNORABLE_LEFTOVER = frozenset({"town", "united"})

REASON_SPORT = "SPORT_MISMATCH"
REASON_FEED = "FEED_TYPE_MISMATCH"
REASON_MARKET = "MARKET_IDENTITY_MISMATCH"
REASON_START = "START_TIME_MISMATCH"
REASON_TEAMS = "MATCH_IDENTITY_MISMATCH"
REASON_AMBIGUOUS = "AMBIGUOUS_EVENT_MATCH"
REASON_BOOKMAKER = "SAME_BOOKMAKER"
REASON_HOME_AWAY = "HOME_AWAY_ORDER_MISMATCH"


def _sport_key(match) -> str:
    sport = (getattr(match, "sport", None) or "").strip().lower()
    if sport == "soccer":
        return "football"
    return sport


def _feed_key(match) -> str:
    return getattr(match, "feed_type", "live") or "live"


class KenyanEventMatcher:
    def __init__(self):
        self.normalizer = TeamNameNormalizer()

    def canonical_team(self, name: str) -> str:
        value = self.normalizer.normalize(name or "")
        if not value:
            return ""
        aliased = TEAM_ALIASES.get(value, value)
        return TEAM_ALIASES.get(aliased, aliased)

    def _tokens(self, canonical: str) -> list:
        return [
            word
            for word in (canonical or "").split()
            if word and word not in _PARTICLES
        ]

    def _token_compat(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        tokens_left = self._tokens(left)
        tokens_right = self._tokens(right)
        if not tokens_left or not tokens_right:
            return False
        shorter, longer = (
            (tokens_left, tokens_right)
            if len(tokens_left) <= len(tokens_right)
            else (tokens_right, tokens_left)
        )
        unused = list(longer)
        for token in shorter:
            matched_at = None
            for index, candidate in enumerate(unused):
                if token == candidate:
                    matched_at = index
                    break
                if (
                    len(token) >= MIN_FUZZY_TOKEN_LEN
                    and len(candidate) >= MIN_FUZZY_TOKEN_LEN
                    and (
                        candidate.startswith(token) or token.startswith(candidate)
                    )
                ):
                    matched_at = index
                    break
            if matched_at is None:
                return False
            unused.pop(matched_at)
        if unused:
            return all(token in _IGNORABLE_LEFTOVER for token in unused)
        return True

    def start_times_compatible(self, match1, match2) -> bool:
        time1 = getattr(match1, "start_time", None)
        time2 = getattr(match2, "start_time", None)
        if time1 is None or time2 is None:
            return True
        try:
            delta = abs(time1 - time2)
        except TypeError:
            return True
        return delta <= START_TIME_TOLERANCE

    def evaluate(self, match1, match2):
        """
        Return (decision, reason, level).
        decision is MATCH or REJECT.
        level is EXACT, TOKEN, or empty.
        """
        if getattr(match1, "bookmaker", None) == getattr(match2, "bookmaker", None):
            return "REJECT", REASON_BOOKMAKER, ""
        if _sport_key(match1) != _sport_key(match2):
            return "REJECT", REASON_SPORT, ""
        if _feed_key(match1) != _feed_key(match2):
            return "REJECT", REASON_FEED, ""
        if kenyan_market_key(match1) != kenyan_market_key(match2):
            return "REJECT", REASON_MARKET, ""
        if not self.start_times_compatible(match1, match2):
            return "REJECT", REASON_START, ""

        home1 = self.canonical_team(match1.home_team)
        away1 = self.canonical_team(match1.away_team)
        home2 = self.canonical_team(match2.home_team)
        away2 = self.canonical_team(match2.away_team)
        if not home1 or not away1 or not home2 or not away2:
            return "REJECT", REASON_TEAMS, ""

        home_exact = home1 == home2
        away_exact = away1 == away2
        if home_exact and away_exact:
            return "MATCH", "EXACT_CANONICAL", "EXACT"

        # Swapped home/away is a different listing, not this fixture.
        if home1 == away2 and away1 == home2:
            return "REJECT", REASON_HOME_AWAY, ""

        home_ok = home_exact or self._token_compat(home1, home2)
        away_ok = away_exact or self._token_compat(away1, away2)
        if home_ok and away_ok:
            return "MATCH", "TOKEN_FALLBACK", "TOKEN"

        return "REJECT", REASON_TEAMS, ""

    def is_same_event(self, match1, match2) -> bool:
        decision, _reason, _level = self.evaluate(match1, match2)
        return decision == "MATCH"


def _start_minute_bucket(start_time):
    if start_time is None:
        return None
    try:
        return int(start_time.timestamp() // 60)
    except (OSError, OverflowError, TypeError, ValueError):
        return str(start_time)


def listing_dedupe_key(match, canonical_team) -> tuple:
    """Same book, market, teams, and kickoff — overlapping catalogue rows."""
    return (
        getattr(match, "bookmaker", None),
        kenyan_market_key(match),
        canonical_team(getattr(match, "home_team", "") or ""),
        canonical_team(getattr(match, "away_team", "") or ""),
        _start_minute_bucket(getattr(match, "start_time", None)),
    )


def dedupe_same_book_listings(matches):
    """
    games1x2 + Get1x2_VZip emit the same 1xBet fixture twice. Two partners
    at one bookmaker make KenyanEventMatcher mark the real pair AMBIGUOUS
    and drop it. Keep the first listing per book/market/teams/kickoff.
    """
    matcher = KenyanEventMatcher()
    kept = []
    seen = set()
    for match in matches:
        key = listing_dedupe_key(match, matcher.canonical_team)
        if key in seen:
            continue
        seen.add(key)
        kept.append(match)
    return kept


def _iter_comparable_pairs(matches):
    """Pairs that can still match under START_TIME_TOLERANCE. O(n * window)."""
    timed = []
    untimed = []
    for index, match in enumerate(matches):
        if getattr(match, "start_time", None) is None:
            untimed.append(index)
        else:
            timed.append(index)
    timed.sort(key=lambda index: matches[index].start_time)
    for position, left in enumerate(timed):
        start_left = matches[left].start_time
        for right in timed[position + 1 :]:
            start_right = matches[right].start_time
            try:
                if start_right - start_left > START_TIME_TOLERANCE:
                    break
            except TypeError:
                pass
            yield left, right
    for offset, left in enumerate(untimed):
        for right in untimed[offset + 1 :]:
            yield left, right
        for right in timed:
            yield left, right


class KenyanMatchFinder:
    def __init__(self):
        self.matcher = KenyanEventMatcher()

    def _event_from_indexes(self, matches, indexes):
        first = matches[indexes[0]]
        event = MatchedEvent(
            sport=first.sport,
            competition=first.competition,
            home_team=first.home_team,
            away_team=first.away_team,
            market=first.market,
        )
        for index in indexes:
            event.add_match(matches[index])
        return event

    def find(self, matches):
        reset_matcher_log_budget()
        if not matches:
            return []

        buckets = defaultdict(list)
        for match in matches:
            buckets[(_feed_key(match), kenyan_market_key(match))].append(match)

        events = []
        for bucket in buckets.values():
            events.extend(self._cluster(bucket))
        return events

    def _cluster(self, matches):
        count = len(matches)
        parent = list(range(count))

        def find_root(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            root_left = find_root(left)
            root_right = find_root(right)
            if root_left != root_right:
                parent[root_right] = root_left

        exact_pairs = []
        token_pairs = []
        for i, j in _iter_comparable_pairs(matches):
            decision, reason, level = self.matcher.evaluate(matches[i], matches[j])
            if decision != "MATCH":
                if reason in (
                    REASON_START,
                    REASON_AMBIGUOUS,
                    REASON_HOME_AWAY,
                    REASON_TEAMS,
                ):
                    log_matcher(
                        event_label(matches[i]),
                        event_label(matches[j]),
                        "REJECT",
                        reason,
                    )
                continue
            pair = (i, j)
            if level == "EXACT":
                exact_pairs.append(pair)
            else:
                token_pairs.append(pair)

        def mark_ambiguous(pairs):
            by_book = defaultdict(lambda: defaultdict(list))
            for i, j in pairs:
                by_book[i][matches[j].bookmaker].append(j)
                by_book[j][matches[i].bookmaker].append(i)
            ambiguous = set()
            for index, books in by_book.items():
                for bookmaker, partners in books.items():
                    if len(partners) <= 1:
                        continue
                    for partner in partners:
                        ambiguous.add(frozenset((index, partner)))
                        log_matcher(
                            event_label(matches[index]),
                            event_label(matches[partner]),
                            "REJECT",
                            REASON_AMBIGUOUS,
                        )
            return ambiguous

        ambiguous_exact = mark_ambiguous(exact_pairs)
        for i, j in exact_pairs:
            if frozenset((i, j)) in ambiguous_exact:
                continue
            union(i, j)

        remaining_token = []
        for i, j in token_pairs:
            if find_root(i) == find_root(j):
                continue
            remaining_token.append((i, j))

        ambiguous_token = mark_ambiguous(remaining_token)
        remaining_token = [
            pair for pair in remaining_token if frozenset(pair) not in ambiguous_token
        ]

        compat_roots = defaultdict(set)
        for i, j in remaining_token:
            root_i = find_root(i)
            root_j = find_root(j)
            if root_i == root_j:
                continue
            compat_roots[root_i].add(root_j)
            compat_roots[root_j].add(root_i)

        merged_roots = set()
        for root, others in list(compat_roots.items()):
            if root in merged_roots:
                continue
            if len(others) != 1:
                if others:
                    log_matcher(
                        event_label(matches[root]),
                        "multiple",
                        "REJECT",
                        REASON_AMBIGUOUS,
                    )
                continue
            other = next(iter(others))
            if len(compat_roots.get(other, ())) != 1:
                continue
            books_root = {
                matches[k].bookmaker
                for k in range(count)
                if find_root(k) == root
            }
            books_other = {
                matches[k].bookmaker
                for k in range(count)
                if find_root(k) == other
            }
            if books_root & books_other:
                log_matcher(
                    event_label(matches[root]),
                    event_label(matches[other]),
                    "REJECT",
                    REASON_AMBIGUOUS,
                )
                continue
            union(root, other)
            merged_roots.add(root)
            merged_roots.add(other)

        grouped = defaultdict(list)
        for index in range(count):
            grouped[find_root(index)].append(index)

        return [self._event_from_indexes(matches, indexes) for indexes in grouped.values()]
