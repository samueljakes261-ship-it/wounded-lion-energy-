"""Serialize Betfair opportunities for the existing /opportunities JSON cache."""
from datetime import datetime, timezone
from typing import Any, Optional

from betfair.models import LIVE, BetfairOpportunity, BetfairRef


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _is_profitable(opportunity: BetfairOpportunity) -> bool:
    if opportunity.status == "MATCHED_NO_VALUE":
        return False
    if opportunity.value_pct is None:
        return False
    return opportunity.value_pct > 0


def serialize_ref(ref: BetfairRef) -> dict[str, Any]:
    return {"bookmaker": ref.bookmaker, "value": ref.value}


def serialize_opportunity(opportunity: BetfairOpportunity) -> dict[str, Any]:
    payload = {
        "opportunityType": "BETFAIR",
        "source": opportunity.source,
        "sourceLabel": opportunity.source_label,
        "clusterId": opportunity.cluster_id,
        "matchClusterId": opportunity.match_cluster_id,
        "homeTeam": opportunity.home_team,
        "awayTeam": opportunity.away_team,
        "startTime": _iso(opportunity.start_time),
        "sport": opportunity.sport,
        "league": opportunity.league,
        "competition": opportunity.league,
        "marketLabel": opportunity.market_label,
        "market": opportunity.market_label,
        "category": opportunity.category,
        "categoryLabel": opportunity.category_label,
        "direction": opportunity.direction,
        "iddaaOdd": opportunity.iddaa_odd,
        "refOdd": opportunity.ref_odd,
        "refBookmaker": opportunity.ref_bookmaker,
        "bestBackBookmaker": opportunity.best_back_bookmaker,
        "backStake": opportunity.back_stake,
        "layStake": opportunity.lay_stake,
        "layLiability": opportunity.lay_liability,
        "commissionRate": opportunity.commission_rate,
        "profitIfBackWins": opportunity.profit_if_back_wins,
        "profitIfBackLoses": opportunity.profit_if_back_loses,
        "guaranteedProfit": opportunity.guaranteed_profit,
        "eventOrientation": opportunity.event_orientation,
        "layAvailableSize": opportunity.lay_available_size,
        "executionGrade": opportunity.execution_grade,
        "refs": [serialize_ref(ref) for ref in opportunity.refs],
        "valuePct": opportunity.value_pct,
        "profitPercentage": opportunity.value_pct,
        "status": opportunity.status,
        "eventMatchScore": opportunity.event_match_score,
        "period": opportunity.period,
        "line": opportunity.line,
        "outcome": opportunity.outcome,
        "isLive": opportunity.is_live,
        "liveClassification": opportunity.live_classification,
        "liveClock": opportunity.live_clock,
        "detectedAt": _iso(opportunity.detected_at),
        "firstSeenAt": _iso(opportunity.first_seen_at),
        "lastUpdatedAt": _iso(opportunity.last_updated_at),
        "isProfitable": _is_profitable(opportunity),
    }
    if opportunity.extra:
        payload["extra"] = opportunity.extra
    return payload


def serialize_snapshot(
    opportunities: list[BetfairOpportunity],
    *,
    last_success_at: float,
    generated_at: Optional[datetime] = None,
    rejected: int = 0,
) -> dict[str, Any]:
    now = generated_at or datetime.now(timezone.utc)
    serialized = [serialize_opportunity(item) for item in opportunities]
    return {
        "generatedAt": _iso(now),
        "lastSuccessAt": last_success_at,
        "rejected": rejected,
        "liveCount": sum(1 for item in opportunities if item.live_classification == LIVE),
        "prematchCount": sum(
            1 for item in opportunities if item.live_classification == "PREMATCH"
        ),
        "unknownCount": sum(
            1 for item in opportunities if item.live_classification == "UNKNOWN"
        ),
        "opportunities": serialized,
    }
