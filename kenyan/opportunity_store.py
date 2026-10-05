"""
Stateful Kenyan opportunity identity and retention.

`KenyanArbitrageEngine.compute_opportunities` is stateless: every API
read rebuilds a new list from whatever matches are currently visible.
LIVE bookmaker pages are incomplete windows, so that list flickers.

This store is Kenyan-only. LIVE and PREMATCH use separate instances so
one feed can never overwrite the other. Identity includes feed type.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from kenyan.config import KENYAN_OPPORTUNITY_RETENTION_SECONDS
from kenyan.matcher import KenyanEventMatcher, _feed_key, _sport_key


_MATCHER = KenyanEventMatcher()


@dataclass
class TrackedKenyanOpportunity:
    identity: str
    opportunity: object
    created_at: float
    updated_at: float
    last_seen_at: float
    is_live: bool

    def odds_tuple(self):
        best = self.opportunity.result.best_odds
        return (best.home_odds, best.draw_odds, best.away_odds)


def _opportunity_feed(opportunity) -> str:
    event = opportunity.event
    for match in getattr(event, "matches", None) or []:
        return _feed_key(match)
    return "live"


def opportunity_identity(opportunity, *, matcher: Optional[KenyanEventMatcher] = None) -> str:
    """
    Canonical Kenyan BACK-vs-BACK identity. Odds are intentionally
    excluded so a price update is the same logical opportunity.
    """

    matcher = matcher or _MATCHER
    event = opportunity.event
    best = opportunity.result.best_odds
    feed = _opportunity_feed(opportunity)
    sport = _sport_key(event)
    home = matcher.canonical_team(event.home_team)
    away = matcher.canonical_team(event.away_team)
    market = (getattr(event, "market", None) or "1X2").strip().lower()
    return "|".join(
        [
            feed,
            sport,
            home,
            away,
            market,
            "BACK_BACK",
            best.home_match.bookmaker,
            best.draw_match.bookmaker,
            best.away_match.bookmaker,
        ]
    )


def _odds_tuple(opportunity):
    best = opportunity.result.best_odds
    return (best.home_odds, best.draw_odds, best.away_odds)


class KenyanOpportunityStore:
    def __init__(self, *, retention_seconds: float = KENYAN_OPPORTUNITY_RETENTION_SECONDS):
        self._retention_seconds = retention_seconds
        self._records: Dict[str, TrackedKenyanOpportunity] = {}

    def apply(
        self,
        computed: Iterable,
        *,
        now: Optional[float] = None,
    ) -> List[TrackedKenyanOpportunity]:
        now = now if now is not None else datetime.now(timezone.utc).timestamp()
        seen = set()

        for opportunity in computed:
            identity = opportunity_identity(opportunity)
            seen.add(identity)
            is_live = _opportunity_feed(opportunity) == "live"
            existing = self._records.get(identity)
            if existing is None:
                self._records[identity] = TrackedKenyanOpportunity(
                    identity=identity,
                    opportunity=opportunity,
                    created_at=now,
                    updated_at=now,
                    last_seen_at=now,
                    is_live=is_live,
                )
                continue

            odds_changed = existing.odds_tuple() != _odds_tuple(opportunity)
            existing.opportunity = opportunity
            existing.last_seen_at = now
            existing.is_live = is_live
            if odds_changed:
                existing.updated_at = now

        expired = [
            identity
            for identity, record in self._records.items()
            if identity not in seen and (now - record.last_seen_at) > self._retention_seconds
        ]
        for identity in expired:
            del self._records[identity]

        return list(self._records.values())
