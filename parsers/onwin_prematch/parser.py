"""OnWin prematch football 1X2 parser.

Uses live extract_event_diff / extract_1x2_market from parsers.onwin.parser
without modifying that module. Live OnWinParser still filters
status == in_progress only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.match import MatchOdds
from parsers.onwin.parser import (
    FOOTBALL_SPORT_ID,
    extract_1x2_market,
    extract_event_diff,
)

LIVE_STATUSES = {"in_progress"}
FINISHED_STATUSES = {
    "finished",
    "ended",
    "closed",
    "cancelled",
    "canceled",
    "abandoned",
}


def unwrap_payload(data):
    if isinstance(data, list) and data:
        return unwrap_payload(data[0])
    if isinstance(data, dict) and "sports" not in data:
        for key in ("result", "data", "payload"):
            inner = data.get(key)
            if isinstance(inner, (dict, list)):
                return unwrap_payload(inner)
    return data


def parse_prematch(data) -> list[MatchOdds]:
    payload = unwrap_payload(data)
    if not isinstance(payload, dict):
        return []
    football = payload.get("sports", {}).get(FOOTBALL_SPORT_ID)
    if not football:
        return []
    collected = datetime.now(timezone.utc)
    matches = []
    for category in (football.get("categories") or {}).values():
        category_name = (category.get("diff") or {}).get("name", "")
        for tournament in (category.get("tournaments") or {}).values():
            competition = (tournament.get("diff") or {}).get("name", category_name)
            events = tournament.get("events") or {}
            if not isinstance(events, dict):
                continue
            for event in events.values():
                fields = extract_event_diff(event)
                if fields is None:
                    continue
                status = fields["status"]
                if status in LIVE_STATUSES or status in FINISHED_STATUSES:
                    continue
                market = extract_1x2_market(event)
                if market is None:
                    continue
                home, draw, away, _updated = market
                start_ms = fields["start_time_ms"]
                if start_ms is None:
                    continue
                start_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                matches.append(
                    MatchOdds(
                        bookmaker="OnWin",
                        competition=competition,
                        sport="football",
                        market="1X2",
                        home_team=fields["home_team"],
                        away_team=fields["away_team"],
                        home_odds=home,
                        draw_odds=draw,
                        away_odds=away,
                        start_time=start_time,
                        collected_at=collected,
                        feed_type="prematch",
                    )
                )
    return matches
