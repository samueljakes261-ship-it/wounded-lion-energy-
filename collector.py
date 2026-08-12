import asyncio
import json
import multiprocessing
from pathlib import Path

from engine.match_finder import MatchFinder
from engine.best_odds_selector import BestOddsSelector
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator
from models.arbitrage_opportunity import ArbitrageOpportunity

from parsers.betkanyon.feed import BetkanyonFeed
from parsers.onwin.feed import OnwinFeed


CACHE_FILE = Path("cached_opportunities.json")


# ============================================================
# ONWIN WORKER
# ============================================================
#
# OnWin uses Playwright Sync API.
# It must therefore run in a completely separate process from
# the asyncio engine.
#
# Do NOT move this function inside collect_opportunities().
# Windows multiprocessing requires it to be module-level.
# ============================================================

def _collect_onwin_worker(queue):
    feed = None

    try:
        feed = OnwinFeed()

        matches = feed.collect_once()

        queue.put({
            "success": True,
            "matches": matches,
            "error": None,
        })

    except Exception as exc:
        queue.put({
            "success": False,
            "matches": [],
            "error": f"{type(exc).__name__}: {exc}",
        })

    finally:
        if feed is not None:
            try:
                feed.close()
            except Exception:
                pass


def _collect_onwin_sync():
    """
    Run the synchronous OnWin Playwright collector in a
    completely separate process.

    Returns:
        list[MatchOdds]
    """

    ctx = multiprocessing.get_context("spawn")

    queue = ctx.Queue()

    process = ctx.Process(
        target=_collect_onwin_worker,
        args=(queue,),
    )

    process.start()

    try:
        # Wait for the worker to return its result.
        result = queue.get()

    finally:
        process.join()

    if not result["success"]:
        raise RuntimeError(
            f"OnWin collection failed: {result['error']}"
        )

    return result["matches"]


# ============================================================
# MAIN COLLECTION PIPELINE
# ============================================================

async def collect_opportunities(bankroll=1000):

    # --------------------------------------------------------
    # Create engine components.
    # --------------------------------------------------------

    finder = MatchFinder()
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    calculator = StakeCalculator()

    # --------------------------------------------------------
    # Collect BetKanyon and OnWin.
    #
    # Orbit is intentionally disabled for now.
    #
    # They are launched concurrently:
    #
    #   BetKanyon -> worker thread
    #   OnWin     -> separate process
    #
    # This means the slow OnWin browser startup does not block
    # the BetKanyon collection.
    # --------------------------------------------------------

    betkanyon = BetkanyonFeed()

    print()
    print("=" * 70)
    print("COLLECTING BOOKMAKER DATA")
    print("=" * 70)
    print()
    print("Orbit: DISABLED")
    print("BetKanyon: ENABLED")
    print("OnWin: ENABLED")
    print()

    betkanyon_task = asyncio.to_thread(
        betkanyon.collect_once
    )

    onwin_task = asyncio.to_thread(
        _collect_onwin_sync
    )

    betkanyon_matches, onwin_matches = await asyncio.gather(
        betkanyon_task,
        onwin_task,
    )

    # --------------------------------------------------------
    # Report collection results.
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("BOOKMAKER COLLECTION COMPLETE")
    print("=" * 70)

    print(
        f"BetKanyon MatchOdds : {len(betkanyon_matches)}"
    )

    print(
        f"OnWin MatchOdds     : {len(onwin_matches)}"
    )

    print(
        f"Total MatchOdds     : "
        f"{len(betkanyon_matches) + len(onwin_matches)}"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # Combine bookmaker MatchOdds.
    # --------------------------------------------------------

    matches = []

    matches.extend(betkanyon_matches)
    matches.extend(onwin_matches)

    # --------------------------------------------------------
    # Match events.
    #
    # This is the existing engine pipeline.
    # The bookmaker-specific parsers have already produced
    # MatchOdds, so from this point onward the normal engine
    # pipeline takes over.
    # --------------------------------------------------------

    matched_events = finder.find(matches)

    print()
    print(
        f"Matched events : {len(matched_events)}"
    )

    # --------------------------------------------------------
    # Detect arbitrage opportunities.
    # --------------------------------------------------------

    opportunities = []

    for event in matched_events:

        best = selector.select(event)

        result = detector.detect(best)

        if not result.arbitrage_exists:
            continue

        stake_plan = calculator.calculate(
            result=result,
            bankroll=bankroll,
        )

        opportunities.append(
            ArbitrageOpportunity(
                event=event,
                result=result,
                stake_plan=stake_plan,
            )
        )

    # --------------------------------------------------------
    # Save opportunities to cache.
    # --------------------------------------------------------

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

                "profitPercentage": round(
                    result.profit_percentage,
                    2,
                ),

                "impliedProbability": round(
                    result.implied_probability,
                    4,
                ),

                "roi": plan.roi,
                "guaranteedProfit": plan.guaranteed_profit,
                "guaranteedReturn": plan.guaranteed_return,
                "totalStake": plan.total_stake,

                "home": {
                    "bookmaker": best.home_match.bookmaker,
                    "odds": best.home_match.home_odds,
                    "stake": plan.home.stake,
                },

                "draw": {
                    "bookmaker": best.draw_match.bookmaker,
                    "odds": best.draw_match.draw_odds,
                    "stake": plan.draw.stake,
                },

                "away": {
                    "bookmaker": best.away_match.bookmaker,
                    "odds": best.away_match.away_odds,
                    "stake": plan.away.stake,
                },
            }
        )

    CACHE_FILE.write_text(
        json.dumps(
            cache,
            indent=4,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print(
        f"ARBITRAGE SCAN COMPLETE | "
        f"Opportunities: {len(opportunities)}"
    )
    print("=" * 70)

    return opportunities


# ============================================================
# CACHE
# ============================================================

def get_cached_opportunities():

    if not CACHE_FILE.exists():
        return []

    return json.loads(
        CACHE_FILE.read_text(
            encoding="utf-8"
        )
    )



