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
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Response

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


def _dt_fields(value, now):
    if value is None:
        return None, None
    try:
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        iso = stamp.isoformat().replace("+00:00", "Z")
        age = max(0.0, (now - stamp).total_seconds())
        return iso, round(age, 1)
    except (TypeError, AttributeError):
        return None, None


def _leg_payload(match, odds, stake, now):
    collected_iso, collected_age = _dt_fields(getattr(match, "collected_at", None), now)
    confirmed_iso, confirmed_age = _dt_fields(getattr(match, "confirmed_at", None), now)
    return {
        "bookmaker": match.bookmaker,
        "odds": odds,
        "stake": stake,
        "collectedAt": collected_iso,
        "confirmedAt": confirmed_iso,
        "oddsAgeSeconds": collected_age,
        "confirmedAgeSeconds": confirmed_age,
    }


def _oldest_constituent_ages(matches, now):
    collected_ages = []
    confirmed_ages = []
    collected_isos = []
    for match in matches:
        if match is None:
            continue
        collected_iso, collected_age = _dt_fields(getattr(match, "collected_at", None), now)
        confirmed_iso, confirmed_age = _dt_fields(getattr(match, "confirmed_at", None), now)
        if collected_age is not None:
            collected_ages.append(collected_age)
            collected_isos.append((collected_age, collected_iso))
        if confirmed_age is not None:
            confirmed_ages.append(confirmed_age)
    oldest_collected = max(collected_ages) if collected_ages else None
    oldest_confirmed = max(confirmed_ages) if confirmed_ages else None
    oldest_iso = None
    if collected_isos:
        oldest_iso = max(collected_isos)[1]
    return oldest_iso, oldest_collected, oldest_confirmed


def serialize_opportunities(opportunities, *, now=None) -> list:
    serialized = []
    now = now or datetime.now(timezone.utc)

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

            last_updated = _iso_utc(updated_at) if updated_at is not None else None
            if two_way:
                constituents = [best.home_match, best.away_match]
            else:
                constituents = [best.home_match, best.draw_match, best.away_match]
            collected_iso, odds_age, confirmed_age = _oldest_constituent_ages(constituents, now)

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
                "updatedAt": last_updated,
                "lastUpdated": last_updated,
                "collectedAt": collected_iso,
                "oddsAgeSeconds": odds_age,
                "confirmedAgeSeconds": confirmed_age,
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
                        "home": _leg_payload(best.home_match, best.home_odds, plan.home.stake, now),
                        "draw": None,
                        "away": _leg_payload(best.away_match, best.away_odds, plan.away.stake, now),
                    }
                )
            else:
                row.update(
                    {
                        "homeLabel": "HOME",
                        "awayLabel": "AWAY",
                        "home": _leg_payload(best.home_match, best.home_odds, plan.home.stake, now),
                        "draw": _leg_payload(best.draw_match, best.draw_odds, plan.draw.stake, now),
                        "away": _leg_payload(best.away_match, best.away_odds, plan.away.stake, now),
                    }
                )

            serialized.append(row)
        except Exception:
            continue

    return serialized


@router.get("/opportunities")
def opportunities(mode: str = "prematch", response: Response = None):
    started = time.monotonic()
    runner = get_runner()

    if mode.upper() == PREMATCH:
        payload = serialize_opportunities(runner.get_prematch_opportunities())
    else:
        payload = serialize_opportunities(runner.get_live_opportunities())

    if response is not None:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Kenyan-Serialize-Ms"] = str(
            round((time.monotonic() - started) * 1000, 2)
        )
        response.headers["X-Kenyan-Count"] = str(len(payload))
    return payload


@router.get("/status")
def status():
    return get_runner().get_engine_status()


def include_kenyan_routes(app):
    """
    Single integration point for api.py: mounts every Kenyan route.
    """

    app.include_router(router)
