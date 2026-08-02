import json
import asyncio
from pathlib import Path

from engine.match_finder import MatchFinder
from engine.best_odds_selector import BestOddsSelector
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator

from models.arbitrage_opportunity import ArbitrageOpportunity


CACHE_FILE = Path("cached_opportunities.json")


finder = MatchFinder()
selector = BestOddsSelector()
detector = ArbitrageDetector()
calculator = StakeCalculator()


async def collect_opportunities(bankroll=1000):

    #
    # Import parsers ONLY when the scanner runs.
    # This prevents Render from importing Playwright just to serve cached data.
    #
    from parsers.orbit.feed import OrbitFeed
    from parsers.betkanyon.feed import BetkanyonFeed

    orbit = OrbitFeed()
    betkanyon = BetkanyonFeed()

    #
    # Collect bookmakers
    #

    await orbit.collect_once()

    await asyncio.to_thread(
        betkanyon.collect_once
    )

    matches = []

    matches.extend(
        orbit.get_match_odds()
    )

    matches.extend(
        betkanyon.get_match_odds()
    )

    #
    # Match events
    #

    matched_events = finder.find(matches)

    opportunities = []

    for event in matched_events:

        best = selector.select(event)

        result = detector.detect(best)

        if not result.arbitrage_exists:
            continue

        stake_plan = calculator.calculate(
            result=result,
            bankroll=bankroll
        )

        opportunities.append(

            ArbitrageOpportunity(

                event=event,

                result=result,

                stake_plan=stake_plan

            )

        )

    #
    # Save cache
    #

    cache = []

    for opportunity in opportunities:

        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan
        best = result.best_odds

        cache.append({

            "sport": event.sport,
            "competition": event.competition,
            "market": event.market,

            "homeTeam": event.home_team,
            "awayTeam": event.away_team,

            "profitPercentage": round(
                result.profit_percentage,
                2
            ),

            "impliedProbability": round(
                result.implied_probability,
                4
            ),

            "roi": plan.roi,
            "guaranteedProfit": plan.guaranteed_profit,
            "guaranteedReturn": plan.guaranteed_return,
            "totalStake": plan.total_stake,

            "home": {
                "bookmaker": best.home_match.bookmaker,
                "odds": best.home_match.home_odds,
                "stake": plan.home.stake
            },

            "draw": {
                "bookmaker": best.draw_match.bookmaker,
                "odds": best.draw_match.draw_odds,
                "stake": plan.draw.stake
            },

            "away": {
                "bookmaker": best.away_match.bookmaker,
                "odds": best.away_match.away_odds,
                "stake": plan.away.stake
            }

        })

    CACHE_FILE.write_text(
        json.dumps(cache, indent=4),
        encoding="utf-8"
    )

    return opportunities


def get_cached_opportunities():

    if not CACHE_FILE.exists():
        return []

    return json.loads(
        CACHE_FILE.read_text(
            encoding="utf-8"
        )
    )