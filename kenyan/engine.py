"""
Kenyan arbitrage engine.

Matching is Kenyan-specific (kenyan.matcher.KenyanMatchFinder) so the
Turkish live 3-character EventMatcher is never used here.

Math reuse: BestOddsSelector, ArbitrageDetector, StakeCalculator stay
unmodified for three-way 1X2. Two-way winner and Over/Under reuse
detect_two_way + calculate_two_way_stakes without touching the Turkish
TARGET_OU_LINE=2.5 filter.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from engine.over_under import calculate_two_way_stakes
from engine.stake_calculator import StakeCalculator
from kenyan.config import KENYAN_BANKROLL, KENYAN_STALE_AFTER_SECONDS
from kenyan.log import event_label, log_arb
from kenyan.markets import (
    FAMILY_TOTAL,
    MARKET_MATCH_WINNER,
    infer_family,
    infer_market_type,
    kenyan_market_key,
    market_label,
    winner_outcome_labels,
)
from kenyan.matcher import (
    START_TIME_TOLERANCE,
    KenyanMatchFinder,
    _sport_key,
    dedupe_same_book_listings,
)
from kenyan.models import (
    KenyanMatchOdds,
    KenyanTwoWayBestOdds,
    KenyanTwoWayLeg,
    KenyanTwoWayOpportunity,
    KenyanTwoWayResult,
    KenyanTwoWayStakePlan,
)
from kenyan.odds import pair_is_valid, triple_is_valid
from models.arbitrage_opportunity import ArbitrageOpportunity
from models.markets import is_1x2_market

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


def _is_three_way(match) -> bool:
    return triple_is_valid(match.home_odds, match.draw_odds, match.away_odds)


def _is_two_way(match) -> bool:
    if _is_three_way(match):
        return False
    return pair_is_valid(match.home_odds, match.away_odds)


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

    markets = {kenyan_market_key(leg) for leg in legs}
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


def _validate_two_way(event, over_match, under_match, now) -> Optional[str]:
    legs = [over_match, under_match]
    if any(leg is None for leg in legs):
        return "MARKET_IDENTITY_MISMATCH"
    if kenyan_market_key(over_match) != kenyan_market_key(under_match):
        return "MARKET_IDENTITY_MISMATCH"
    if _sport_key(over_match) != _sport_key(under_match):
        return "MATCH_IDENTITY_MISMATCH"
    feeds = {(getattr(leg, "feed_type", "live") or "live") for leg in legs}
    if len(feeds) != 1:
        return "MATCH_IDENTITY_MISMATCH"
    if over_match.bookmaker == under_match.bookmaker:
        return "CLUSTER_MISMATCH"
    times = [leg.start_time for leg in legs if getattr(leg, "start_time", None)]
    if times and (max(times) - min(times)) > START_TIME_TOLERANCE:
        return "START_TIME_MISMATCH"
    for leg in legs:
        if not pair_is_valid(leg.home_odds, leg.away_odds):
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
    ) -> list:
        if not matches:
            return []

        now = now or datetime.now(timezone.utc)
        matches = dedupe_same_book_listings(matches)
        usable = []
        for match in matches:
            if _is_three_way(match):
                pass
            elif _is_two_way(match):
                pass
            else:
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

            sample = event.matches[0]
            if _is_three_way(sample):
                opportunity = self._compute_three_way(event, bankroll=bankroll, now=now)
            elif _is_two_way(sample):
                opportunity = self._compute_two_way(event, bankroll=bankroll, now=now)
            else:
                continue
            if opportunity is not None:
                opportunities.append(opportunity)

        return opportunities

    def _compute_three_way(self, event, *, bankroll, now):
        try:
            best = self._selector.select(event)
        except NoBackableOddsError:
            return None

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
            return None

        result = self._detector.detect(best)
        if not result.arbitrage_exists:
            return None

        stake_plan = self._calculator.calculate(result=result, bankroll=bankroll)
        log_arb(
            event=f"{event.home_team} vs {event.away_team}",
            market=event.market,
            decision="VALID",
            selection=f"HOME:{best.home_match.bookmaker}",
        )
        return ArbitrageOpportunity(event=event, result=result, stake_plan=stake_plan)

    def _compute_two_way(self, event, *, bankroll, now):
        try:
            best = self._selector.select_over_under(event)
        except NoBackableOddsError:
            return None

        reason = _validate_two_way(event, best.over_match, best.under_match, now)
        if reason:
            log_arb(
                event=f"{event.home_team} vs {event.away_team}",
                market=event.market,
                decision="REJECT",
                reason=reason,
            )
            return None

        implied, exists, profit = self._detector.detect_two_way(
            best.over_odds, best.under_odds
        )
        if not exists:
            return None

        stakes = calculate_two_way_stakes(best.over_odds, best.under_odds, bankroll)
        sample = event.matches[0]
        if infer_family(sample) == FAMILY_TOTAL:
            home_label, away_label = "OVER", "UNDER"
        elif infer_market_type(sample) == MARKET_MATCH_WINNER:
            home_label, away_label = winner_outcome_labels(sample)
        else:
            home_label, away_label = "HOME", "AWAY"

        result = KenyanTwoWayResult(
            best_odds=KenyanTwoWayBestOdds(
                home_match=best.over_match,
                away_match=best.under_match,
            ),
            implied_probability=implied,
            arbitrage_exists=True,
            profit_percentage=profit,
        )
        plan = KenyanTwoWayStakePlan(
            home=KenyanTwoWayLeg(
                outcome=home_label,
                bookmaker=best.over_match.bookmaker,
                odds=best.over_odds,
                stake=stakes["over_stake"],
            ),
            away=KenyanTwoWayLeg(
                outcome=away_label,
                bookmaker=best.under_match.bookmaker,
                odds=best.under_odds,
                stake=stakes["under_stake"],
            ),
            total_stake=stakes["total_stake"],
            guaranteed_return=stakes["guaranteed_return"],
            guaranteed_profit=stakes["guaranteed_profit"],
            roi=stakes["roi"],
        )
        log_arb(
            event=f"{event.home_team} vs {event.away_team}",
            market=market_label(sample),
            decision="VALID",
            selection=f"{home_label}:{best.over_match.bookmaker}",
        )
        return KenyanTwoWayOpportunity(
            event=event,
            result=result,
            stake_plan=plan,
            home_label=home_label,
            away_label=away_label,
        )
