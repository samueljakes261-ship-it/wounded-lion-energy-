"""
Kenyan arbitrage engine.

Matching is Kenyan-specific (kenyan.matcher.KenyanMatchFinder) so the
Turkish live 3-character EventMatcher is never used here.

Math reuse: BestOddsSelector, ArbitrageDetector, StakeCalculator stay
unmodified. An opportunity is only created after identity validation
(same event, same 1X2 market, compatible start times, one cluster per
bookmaker, current valid odds).
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from engine.stake_calculator import StakeCalculator
from kenyan.config import KENYAN_BANKROLL, KENYAN_STALE_AFTER_SECONDS
from kenyan.log import event_label, log_arb
from kenyan.matcher import START_TIME_TOLERANCE, KenyanMatchFinder, _sport_key
from kenyan.models import KenyanMatchOdds
from kenyan.odds import triple_is_valid
from models.arbitrage_opportunity import ArbitrageOpportunity
from models.markets import arb_group_key, is_1x2_market

MIN_BOOKMAKERS_FOR_ARBITRAGE = 2


def _is_stale(match, now) -> bool:
    collected = getattr(match, "collected_at", None)
    if collected is None:
        return False
    try:
        age = (now - collected).total_seconds()
    except TypeError:
        return False
    return age > KENYAN_STALE_AFTER_SECONDS


def validate_opportunity(event, best, now) -> Optional[str]:
    """Return a rejection reason, or None if the opportunity is implementable."""
    legs = [best.home_match, best.draw_match, best.away_match]
    if any(leg is None for leg in legs):
        return "MARKET_IDENTITY_MISMATCH"

    sports = {_sport_key(leg) for leg in legs}
    if len(sports) != 1:
        return "MATCH_IDENTITY_MISMATCH"

    feeds = {(getattr(leg, "feed_type", "live") or "live") for leg in legs}
    if len(feeds) != 1:
        return "MATCH_IDENTITY_MISMATCH"

    markets = {arb_group_key(leg) for leg in legs}
    if len(markets) != 1 or not all(is_1x2_market(leg.market) for leg in legs):
        return "MARKET_IDENTITY_MISMATCH"

    by_book = defaultdict(list)
    for leg in legs:
        by_book[leg.bookmaker].append(leg)
    for _book, rows in by_book.items():
        event_ids = {getattr(row, "event_id", "") or "" for row in rows}
        clusters = {getattr(row, "cluster_id", "") or "" for row in rows}
        if len(event_ids) > 1:
            return "CLUSTER_MISMATCH"
        if len(clusters) > 1:
            return "CLUSTER_MISMATCH"

    times = [leg.start_time for leg in legs if getattr(leg, "start_time", None)]
    if times and (max(times) - min(times)) > START_TIME_TOLERANCE:
        return "START_TIME_MISMATCH"

    for leg in legs:
        if not triple_is_valid(leg.home_odds, leg.draw_odds, leg.away_odds):
            return "INVALID_ODDS"
        if _is_stale(leg, now):
            return "STALE_ODDS"

    books_in_event = [match.bookmaker for match in event.matches]
    if len(books_in_event) != len(set(books_in_event)):
        return "CLUSTER_MISMATCH"

    return None


class KenyanArbitrageEngine:
    def __init__(self):
        self._finder = KenyanMatchFinder()
        self._selector = BestOddsSelector()
        self._detector = ArbitrageDetector()
        self._calculator = StakeCalculator()

    def compute_opportunities(
        self,
        matches: List[KenyanMatchOdds],
        *,
        bankroll: float = KENYAN_BANKROLL,
        now=None,
    ) -> List[ArbitrageOpportunity]:
        if not matches:
            return []

        now = now or datetime.now(timezone.utc)
        usable = []
        for match in matches:
            if not triple_is_valid(match.home_odds, match.draw_odds, match.away_odds):
                log_arb(
                    event=event_label(match),
                    market=getattr(match, "market", "1X2"),
                    decision="REJECT",
                    reason="INVALID_ODDS",
                )
                continue
            if _is_stale(match, now):
                log_arb(
                    event=event_label(match),
                    market=getattr(match, "market", "1X2"),
                    decision="REJECT",
                    reason="STALE_ODDS",
                )
                continue
            usable.append(match)

        matched_events = self._finder.find(usable)
        opportunities = []

        for event in matched_events:
            distinct_bookmakers = {match.bookmaker for match in event.matches}
            if len(distinct_bookmakers) < MIN_BOOKMAKERS_FOR_ARBITRAGE:
                continue

            try:
                best = self._selector.select(event)
            except NoBackableOddsError:
                continue

            reason = validate_opportunity(event, best, now)
            if reason:
                log_arb(
                    event=f"{event.home_team} vs {event.away_team}",
                    market=event.market,
                    decision="REJECT",
                    reason=reason,
                    selection=f"HOME:{best.home_match.bookmaker}",
                    extra=f"DRAW:{best.draw_match.bookmaker} AWAY:{best.away_match.bookmaker}",
                )
                continue

            result = self._detector.detect(best)
            if not result.arbitrage_exists:
                continue

            stake_plan = self._calculator.calculate(result=result, bankroll=bankroll)
            log_arb(
                event=f"{event.home_team} vs {event.away_team}",
                market=event.market,
                decision="VALID",
                selection=f"HOME:{best.home_match.bookmaker}",
            )
            opportunities.append(
                ArbitrageOpportunity(event=event, result=result, stake_plan=stake_plan)
            )

        return opportunities
