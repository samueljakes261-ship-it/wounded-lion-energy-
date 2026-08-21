"""Prematch matching + arbitrage using the existing live engine classes.

Writes a separate cache so /opportunities (live) is unchanged.
"""

from datetime import datetime, timezone
from pathlib import Path

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from engine.stake_calculator import StakeCalculator
from models.arbitrage_opportunity import ArbitrageOpportunity
from prematch.matcher import PrematchMatchFinder

PREMATCH_CACHE_FILE = Path("cached_prematch_opportunities.json")
# Prematch snapshots can take longer than a live poll (many tournament
# fetches). 15 minutes keeps a completed snapshot usable until the next
# leftover-wait refresh without treating in-cycle timestamps as stale.
PREMATCH_MAX_ODDS_AGE_SECONDS = 900.0


def _iso_dt(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _filter_stale(matches, now_dt):
    kept = []
    dropped = 0
    for match in matches:
        collected = getattr(match, "collected_at", None)
        if collected is None:
            kept.append(match)
            continue
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        age = (now_dt - collected).total_seconds()
        if age > PREMATCH_MAX_ODDS_AGE_SECONDS:
            dropped += 1
            continue
        kept.append(match)
    return kept, dropped


def _leg_label(match, outcome):
    price = getattr(match, f"{outcome}_odds")
    if match.bookmaker.lower() == "orbit":
        side = match.side or "?"
        return f"Orbit {side} @ {price}"
    return f"{match.bookmaker} @ {price}"


def _opportunity_is_source_safe(opportunity):
    best = opportunity.result.best_odds
    legs = (best.home_match, best.draw_match, best.away_match)
    books = {leg.bookmaker for leg in legs}
    if len(books) < 2:
        return False, "all three legs from one bookmaker"
    for leg in legs:
        if getattr(leg, "feed_type", "prematch") != "prematch":
            return False, "non-prematch leg"
        if leg.bookmaker.lower() == "orbit" and leg.side not in ("BACK", "LAY"):
            return False, "Orbit leg missing BACK/LAY"
    return True, "VERIFIED"


def build_prematch_opportunities(matches, bankroll=1000):
    finder = PrematchMatchFinder()
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    calculator = StakeCalculator()

    matched_events = finder.find(matches)
    opportunities = []
    for event in matched_events:
        try:
            best = selector.select(event)
        except NoBackableOddsError:
            continue
        result = detector.detect(best)
        if not result.arbitrage_exists:
            continue
        stake_plan = calculator.calculate(result=result, bankroll=bankroll)
        opportunity = ArbitrageOpportunity(
            event=event, result=result, stake_plan=stake_plan
        )
        ok, reason = _opportunity_is_source_safe(opportunity)
        best = opportunity.result.best_odds
        print("[PREMATCH ARB]")
        print(f"Event: {event.home_team} vs {event.away_team}")
        print(f"HOME: {_leg_label(best.home_match, 'home')}")
        print(f"DRAW: {_leg_label(best.draw_match, 'draw')}")
        print(f"AWAY: {_leg_label(best.away_match, 'away')}")
        print(f"ROI: {stake_plan.roi}")
        if not ok:
            print(f"Confidence: REJECTED ({reason})")
            continue
        print("Confidence: VERIFIED")
        opportunities.append(opportunity)
    return matched_events, opportunities


def serialize_opportunities(opportunities, generated_at_dt=None):
    generated_at_dt = generated_at_dt or datetime.now(timezone.utc)
    cache = []
    for opportunity in opportunities:
        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan
        best = result.best_odds
        cache.append(
            {
                "sport": event.sport,
                "competition": event.competition,
                "market": event.market,
                "homeTeam": event.home_team,
                "awayTeam": event.away_team,
                "feedType": "prematch",
                "profitPercentage": round(result.profit_percentage, 2),
                "impliedProbability": round(result.implied_probability, 4),
                "roi": plan.roi,
                "guaranteedProfit": plan.guaranteed_profit,
                "guaranteedReturn": plan.guaranteed_return,
                "totalStake": plan.total_stake,
                "generatedAt": _iso_dt(generated_at_dt),
                "home": {
                    "bookmaker": best.home_match.bookmaker,
                    "odds": best.home_match.home_odds,
                    "stake": plan.home.stake,
                    "side": best.home_match.side,
                    "market": best.home_match.market,
                    "collectedAt": _iso_dt(best.home_match.collected_at),
                },
                "draw": {
                    "bookmaker": best.draw_match.bookmaker,
                    "odds": best.draw_match.draw_odds,
                    "stake": plan.draw.stake,
                    "side": best.draw_match.side,
                    "market": best.draw_match.market,
                    "collectedAt": _iso_dt(best.draw_match.collected_at),
                },
                "away": {
                    "bookmaker": best.away_match.bookmaker,
                    "odds": best.away_match.away_odds,
                    "stake": plan.away.stake,
                    "side": best.away_match.side,
                    "market": best.away_match.market,
                    "collectedAt": _iso_dt(best.away_match.collected_at),
                },
            }
        )
    return cache
