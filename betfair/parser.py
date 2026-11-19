"""
Parse the Betfair valuebets payload.

The source already calculated stakes/profits/value. This module only
validates structure, classifies LIVE vs PREMATCH from `is_live`, and
preserves source fields. A single malformed record does not discard
the rest of a valid snapshot.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from betfair.config import SOURCE_ID, SOURCE_LABEL
from betfair.models import (
    LIVE,
    PREMATCH,
    UNKNOWN,
    BetfairOpportunity,
    BetfairRef,
)

REQUIRED_STRING_FIELDS = (
    "home_team",
    "away_team",
    "sport_key",
    "league",
    "market_label",
    "direction",
    "ref_bookmaker",
    "best_back_bookmaker",
    "status",
    "outcome",
)

REQUIRED_TIMESTAMP_FIELDS = (
    "start_time",
    "detected_at",
    "first_seen_at",
    "last_updated_at",
)

_LIST_KEYS = (
    "items",
    "data",
    "opportunities",
    "results",
    "valuebets",
    "records",
    "bets",
)

_KNOWN_FIELDS = {
    "cluster_id",
    "match_cluster_id",
    "home_team",
    "away_team",
    "start_time",
    "sport_key",
    "sport",
    "league",
    "market_label",
    "category",
    "category_label",
    "direction",
    "iddaa_odd",
    "ref_odd",
    "ref_bookmaker",
    "best_back_bookmaker",
    "back_stake",
    "lay_stake",
    "lay_liability",
    "commission_rate",
    "profit_if_back_wins",
    "profit_if_back_loses",
    "guaranteed_profit",
    "event_orientation",
    "lay_available_size",
    "execution_grade",
    "refs",
    "value_pct",
    "status",
    "event_match_score",
    "period",
    "line",
    "outcome",
    "is_live",
    "live_clock",
    "detected_at",
    "first_seen_at",
    "last_updated_at",
}


class ParseResult:
    def __init__(
        self,
        *,
        opportunities: list[BetfairOpportunity],
        rejected: int,
        error: Optional[str] = None,
        raw_count: int = 0,
    ):
        self.opportunities = opportunities
        self.rejected = rejected
        self.error = error
        self.raw_count = raw_count

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def live_count(self) -> int:
        return sum(1 for item in self.opportunities if item.live_classification == LIVE)

    @property
    def prematch_count(self) -> int:
        return sum(1 for item in self.opportunities if item.live_classification == PREMATCH)

    @property
    def unknown_count(self) -> int:
        return sum(1 for item in self.opportunities if item.live_classification == UNKNOWN)


def extract_records(payload: Any) -> tuple[Optional[list], Optional[str]]:
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        return None, f"unexpected JSON type: {type(payload).__name__}"

    for key in _LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value, None

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in _LIST_KEYS:
            value = nested.get(key)
            if isinstance(value, list):
                return value, None

    if "home_team" in payload or "homeTeam" in payload:
        return [payload], None

    return None, "expected a list of opportunities"


def classify_is_live(value: Any, *, present: bool) -> tuple[Optional[bool], str]:
    """
    Primary LIVE vs PREMATCH classification.

    true  -> LIVE
    false -> PREMATCH
    missing/malformed -> UNKNOWN (never silently placed in either bucket)
    """
    if not present:
        return None, UNKNOWN
    if isinstance(value, bool):
        return value, LIVE if value else PREMATCH
    if isinstance(value, (int, float)) and value in (0, 1) and type(value) is not bool:
        # 1/0 are accepted as boolean-like; other numbers are malformed.
        flag = bool(int(value))
        return flag, LIVE if flag else PREMATCH
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True, LIVE
        if lowered in ("false", "no", "0"):
            return False, PREMATCH
    return None, UNKNOWN


def parse_utc_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_string(record: dict, field: str) -> Optional[str]:
    value = record.get(field)
    if value is None:
        value = record.get(_camel(field))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


def _parse_refs(value: Any) -> list[BetfairRef]:
    if not isinstance(value, list):
        return []
    refs: list[BetfairRef] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        bookmaker = item.get("bookmaker") or item.get("name")
        if not bookmaker:
            continue
        refs.append(
            BetfairRef(
                bookmaker=str(bookmaker),
                value=_optional_float(item.get("value", item.get("odd", item.get("odds")))),
            )
        )
    return refs


def _live_clock(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def parse_record(record: Any) -> Optional[BetfairOpportunity]:
    if not isinstance(record, dict):
        return None

    strings = {}
    for field in REQUIRED_STRING_FIELDS:
        text = _required_string(record, field)
        if text is None and field == "sport_key":
            text = _required_string(record, "sport")
        if text is None:
            return None
        strings[field] = text

    timestamps = {}
    for field in REQUIRED_TIMESTAMP_FIELDS:
        raw = record.get(field, record.get(_camel(field)))
        parsed = parse_utc_datetime(raw)
        if parsed is None:
            return None
        timestamps[field] = parsed

    present = "is_live" in record or "isLive" in record
    raw_live = record["is_live"] if "is_live" in record else record.get("isLive")
    is_live, classification = classify_is_live(raw_live, present=present)

    extra = {
        key: value
        for key, value in record.items()
        if key not in _KNOWN_FIELDS and key != "isLive"
    }

    return BetfairOpportunity(
        source=SOURCE_ID,
        source_label=SOURCE_LABEL,
        cluster_id=str(record.get("cluster_id") or record.get("clusterId") or ""),
        match_cluster_id=str(
            record.get("match_cluster_id") or record.get("matchClusterId") or ""
        ),
        home_team=strings["home_team"],
        away_team=strings["away_team"],
        start_time=timestamps["start_time"],
        sport=strings["sport_key"],
        league=strings["league"],
        market_label=strings["market_label"],
        category=_required_string(record, "category"),
        category_label=_required_string(record, "category_label"),
        direction=strings["direction"],
        iddaa_odd=_optional_float(record.get("iddaa_odd", record.get("iddaaOdd"))),
        ref_odd=_optional_float(record.get("ref_odd", record.get("refOdd"))),
        ref_bookmaker=strings["ref_bookmaker"],
        best_back_bookmaker=strings["best_back_bookmaker"],
        back_stake=_optional_float(record.get("back_stake", record.get("backStake"))),
        lay_stake=_optional_float(record.get("lay_stake", record.get("layStake"))),
        lay_liability=_optional_float(
            record.get("lay_liability", record.get("layLiability"))
        ),
        commission_rate=_optional_float(
            record.get("commission_rate", record.get("commissionRate"))
        ),
        profit_if_back_wins=_optional_float(
            record.get("profit_if_back_wins", record.get("profitIfBackWins"))
        ),
        profit_if_back_loses=_optional_float(
            record.get("profit_if_back_loses", record.get("profitIfBackLoses"))
        ),
        guaranteed_profit=_optional_float(
            record.get("guaranteed_profit", record.get("guaranteedProfit"))
        ),
        event_orientation=_required_string(record, "event_orientation"),
        lay_available_size=_optional_float(
            record.get("lay_available_size", record.get("layAvailableSize"))
        ),
        execution_grade=_required_string(record, "execution_grade"),
        refs=_parse_refs(record.get("refs")),
        value_pct=_optional_float(record.get("value_pct", record.get("valuePct"))),
        status=strings["status"],
        event_match_score=_optional_float(
            record.get("event_match_score", record.get("eventMatchScore"))
        ),
        period=_required_string(record, "period"),
        line=_optional_float(record.get("line")),
        outcome=strings["outcome"],
        is_live=is_live,
        live_classification=classification,
        live_clock=_live_clock(record.get("live_clock", record.get("liveClock"))),
        detected_at=timestamps["detected_at"],
        first_seen_at=timestamps["first_seen_at"],
        last_updated_at=timestamps["last_updated_at"],
        extra=extra,
    )


def dedupe_opportunities(
    opportunities: list[BetfairOpportunity],
) -> list[BetfairOpportunity]:
    """Keep distinct markets/outcomes. Identity is cluster_id, not team names."""
    by_id: dict[str, BetfairOpportunity] = {}
    for item in opportunities:
        by_id[item.identity] = item
    return list(by_id.values())


def parse_payload(payload: Any) -> ParseResult:
    records, error = extract_records(payload)
    if error:
        return ParseResult(opportunities=[], rejected=0, error=error, raw_count=0)

    parsed: list[BetfairOpportunity] = []
    rejected = 0
    for record in records:
        item = parse_record(record)
        if item is None:
            rejected += 1
            continue
        parsed.append(item)

    return ParseResult(
        opportunities=dedupe_opportunities(parsed),
        rejected=rejected,
        error=None,
        raw_count=len(records),
    )
