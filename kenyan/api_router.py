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
"""
from datetime import datetime, timezone

from fastapi import APIRouter

from kenyan.config import PREMATCH
from kenyan.markets import market_label
from kenyan.models import KenyanTwoWayOpportunity
from kenyan.opportunity_store import TrackedKenyanOpportunity, opportunity_identity
from kenyan.runner import get_runner

router = APIRouter(prefix="/kenyan", tags=["kenyan"])


def _iso_utc(epoch_seconds) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _sample_match(opportunity):
    event = opportunity.event
    matches = getattr(event, "matches", None) or []
    return matches[0] if matches else None


def serialize_opportunities(opportunities) -> list:
    serialized = []

    for item in opportunities:
        try:
            if isinstance(item, TrackedKenyanOpportunity):
                opportunity = item.opportunity
                identity = item.identity
                created_at = item.created_at
                updated_at = item.updated_at
                is_live = item.is_live
            else:
                opportunity = item
                identity = opportunity_identity(opportunity)
                created_at = updated_at = None
                is_live = any(
                    getattr(match, "status", "") == "LIVE"
                    for match in (opportunity.event.matches or [])
                )

            event = opportunity.event
            result = opportunity.result
            plan = opportunity.stake_plan
            best = result.best_odds
            sample = _sample_match(opportunity)
            label = market_label(sample) if sample is not None else (event.market or "Match Winner")
            two_way = isinstance(opportunity, KenyanTwoWayOpportunity) or getattr(
                opportunity, "outcome_count", 3
            ) == 2

            row = {
                "opportunityId": identity,
                "opportunityType": "BACK_BACK",
                "isLive": is_live,
                "sport": event.sport,
                "competition": event.competition,
                "market": event.market,
                "marketLabel": label,
                "line": getattr(sample, "line", None) if sample is not None else None,
                "period": getattr(sample, "period", None) if sample is not None else None,
                "outcomeCount": 2 if two_way else 3,
                "homeTeam": event.home_team,
                "awayTeam": event.away_team,
                "profitPercentage": round(result.profit_percentage, 2),
                "roi": plan.roi,
                "guaranteedProfit": plan.guaranteed_profit,
                "guaranteedReturn": plan.guaranteed_return,
                "totalStake": plan.total_stake,
                "createdAt": _iso_utc(created_at) if created_at is not None else None,
                "updatedAt": _iso_utc(updated_at) if updated_at is not None else None,
            }

            if two_way:
                home_label = getattr(opportunity, "home_label", None) or getattr(
                    plan.home, "outcome", "HOME"
                )
                away_label = getattr(opportunity, "away_label", None) or getattr(
                    plan.away, "outcome", "AWAY"
                )
                row.update(
                    {
                        "homeLabel": home_label,
                        "awayLabel": away_label,
                        "home": {
                            "bookmaker": best.home_match.bookmaker,
                            "odds": best.home_odds,
                            "stake": plan.home.stake,
                        },
                        "draw": None,
                        "away": {
                            "bookmaker": best.away_match.bookmaker,
                            "odds": best.away_odds,
                            "stake": plan.away.stake,
                        },
                    }
                )
            else:
                row.update(
                    {
                        "homeLabel": "HOME",
                        "awayLabel": "AWAY",
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

            serialized.append(row)
        except Exception:
            continue

    return serialized


@router.get("/opportunities")
def opportunities(mode: str = "prematch"):
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
