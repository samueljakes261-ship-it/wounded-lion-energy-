"""
Isolated FastAPI routes for the Kenyan Bookmakers section.

Mounted into the existing `api.py` app via a single, additive
`app.include_router(kenyan_router)` call -- see the small, clearly
marked addition at the bottom of api.py. No existing route, model, or
behavior in api.py is changed.

Endpoints:
    POST /kenyan/auth          -- exchange the access code for a
                                   short-lived session token. Never
                                   echoes the submitted code back.
    GET  /kenyan/opportunities -- Kenyan BACK-vs-BACK opportunities for
                                   ?mode=live or ?mode=prematch.
                                   Requires a valid session token.
    GET  /kenyan/status        -- per-worker health. Requires a valid
                                   session token.

None of these endpoints, their responses, or their logs ever include
the access code (correct or incorrect) or any part of it.
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from kenyan.access import issue_session_token, verify_access_code, verify_session_token
from kenyan.config import PREMATCH
from kenyan.runner import get_runner

logger = logging.getLogger("kenyan")


class AccessCodeRequest(BaseModel):
    code: str


class AccessCodeResponse(BaseModel):
    token: str
    expires_at: float


def require_session(authorization: str = Header(default=None)) -> None:
    """
    FastAPI dependency: raises 401 unless `Authorization: Bearer
    <token>` carries a currently-valid Kenyan session token. The 401
    response never explains *why* the token was rejected (missing,
    malformed, expired, tampered) -- all of those look identical to
    the caller, so nothing about the gate is discoverable by probing
    error messages.
    """

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer "):].strip()

    if not verify_session_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# `/auth` is intentionally NOT behind `require_session` (that would be
# circular -- it is how a session is obtained in the first place).
# Every other route in this router is gated.
router = APIRouter(prefix="/kenyan", tags=["kenyan"])
gated_router = APIRouter(
    prefix="/kenyan", tags=["kenyan"], dependencies=[Depends(require_session)]
)


@router.post("/auth", response_model=AccessCodeResponse)
def authenticate(request: AccessCodeRequest):
    is_correct = verify_access_code(request.code)

    # Logged ONLY as a boolean outcome -- never the submitted value,
    # never a partial-match hint.
    logger.info("kenyan access attempt: %s", "granted" if is_correct else "denied")

    if not is_correct:
        raise HTTPException(status_code=401, detail="Unauthorized")

    session = issue_session_token()
    return AccessCodeResponse(token=session.token, expires_at=session.expires_at)


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


@gated_router.get("/opportunities")
def opportunities(mode: str = "live"):
    runner = get_runner()

    if mode.upper() == PREMATCH:
        return serialize_opportunities(runner.get_prematch_opportunities())

    return serialize_opportunities(runner.get_live_opportunities())


@gated_router.get("/status")
def status():
    return get_runner().get_engine_status()


def include_kenyan_routes(app):
    """
    Single integration point for api.py: mounts every Kenyan route
    (public `/auth` + gated `/opportunities` and `/status`) without
    api.py needing to know anything about the access-gate internals.
    """

    app.include_router(router)
    app.include_router(gated_router)
