"""
Isolated FastAPI routes for the Kenyan Bookmakers section.

Mounted into the existing `api.py` app via a single, additive
`app.include_router(kenyan_router)` call -- see the small, clearly
marked addition at the bottom of api.py. No existing route, model, or
behavior in api.py is changed.

Endpoints:
    GET /kenyan/opportunities -- Kenyan BACK-vs-BACK opportunities for
                                  ?mode=live or ?mode=prematch.
    GET /kenyan/status        -- per-worker health.

NOTE ON ACCESS CONTROL: this section previously required an access
code (POST /kenyan/auth -> short-lived session token, checked via a
`require_session` dependency on the two routes above). That gate was
removed at explicit user request so the "KENYAN BOOKMAKERS" nav link
goes straight to the opportunities view. The underlying
code/hash/session-token machinery still lives, untouched, in
kenyan/access.py if this ever needs to be re-enabled -- re-attaching
it here would just mean adding back a `dependencies=[Depends(...)]`
router (see git history for the exact prior wiring) without touching
kenyan/access.py itself.
"""
from fastapi import APIRouter

from kenyan.config import PREMATCH
from kenyan.runner import get_runner

router = APIRouter(prefix="/kenyan", tags=["kenyan"])


def serialize_opportunities(opportunities) -> list:
    serialized = []

    for opportunity in opportunities:
        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan
        best = result.best_odds

        serialized.append(
            {
                "sport": event.sport,
                "competition": event.competition,
                "market": event.market,
                "homeTeam": event.home_team,
                "awayTeam": event.away_team,
                "profitPercentage": round(result.profit_percentage, 2),
                "roi": plan.roi,
                "guaranteedProfit": plan.guaranteed_profit,
                "guaranteedReturn": plan.guaranteed_return,
                "totalStake": plan.total_stake,
                "home": {
                    "bookmaker": best.home_match.bookmaker,
                    "odds": best.home_odds,
                    "stake": plan.home.stake,
                },
                "draw": {
                    "bookmaker": best.draw_match.bookmaker,
                    "odds": best.draw_odds,
                    "stake": plan.draw.stake,
                },
                "away": {
                    "bookmaker": best.away_match.bookmaker,
                    "odds": best.away_odds,
                    "stake": plan.away.stake,
                },
            }
        )

    return serialized


@router.get("/opportunities")
def opportunities(mode: str = "live"):
    runner = get_runner()

    if mode.upper() == PREMATCH:
        return serialize_opportunities(runner.get_prematch_opportunities())

    return serialize_opportunities(runner.get_live_opportunities())


@router.get("/status")
def status():
    return get_runner().get_engine_status()


def include_kenyan_routes(app):
    """
    Single integration point for api.py: mounts every Kenyan route.
    """

    app.include_router(router)
