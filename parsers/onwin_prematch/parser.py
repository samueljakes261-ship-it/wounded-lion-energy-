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
from models.markets import CANONICAL_OU_MARKET, TARGET_OU_LINE, parse_ou_line_from_name

_MIN_OU_ODDS = 1.01
_MAX_OU_ODDS = 100.0

LIVE_STATUSES = {"in_progress"}
FINISHED_STATUSES = {
    "finished",
    "ended",
    "closed",
    "cancelled",
    "canceled",
    "abandoned",
}


def extract_ou_markets(event: dict) -> list:
    """Pull Over/Under lines from the same normal_time--0 scope as 1X2.

    OnWin 1X2 uses outcome::p1/draw/p2. Totals use over/under coefficients
    on the same outcomes map (see HANDOFF.md throw_in_ou over/under names).
    The line is read from the market key (e.g. a '...2.5' suffix). No
    market id is hardcoded. Missing markets yield an empty list.
    """
    markets = (
        event.get("scopes", {}).get("normal_time--0", {}).get("markets") or {}
    )
    if not isinstance(markets, dict):
        return []
    found = []
    for key, market in markets.items():
        if not isinstance(market, dict):
            continue
        outcomes = market.get("outcomes") or {}
        if not isinstance(outcomes, dict):
            continue
        over = outcomes.get("outcome::over") or outcomes.get("over")
        under = outcomes.get("outcome::under") or outcomes.get("under")
        if not isinstance(over, dict) or not isinstance(under, dict):
            continue
        over_odds = over.get("coefficient")
        under_odds = under.get("coefficient")
        if over_odds is None or under_odds is None:
            continue
        line = parse_ou_line_from_name(str(key))
        if line != TARGET_OU_LINE:
            continue
        try:
            over_price = float(over_odds)
            under_price = float(under_odds)
        except (TypeError, ValueError):
            continue
        if not (
            _MIN_OU_ODDS <= over_price <= _MAX_OU_ODDS
            and _MIN_OU_ODDS <= under_price <= _MAX_OU_ODDS
        ):
            continue
        found.append((line, over_price, under_price))
    return found


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
                start_ms = fields["start_time_ms"]
                if start_ms is None:
                    continue
                start_time = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                market = extract_1x2_market(event)
                if market is not None:
                    home, draw, away, _updated = market
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
                for line, over_odds, under_odds in extract_ou_markets(event):
                    matches.append(
                        MatchOdds(
                            bookmaker="OnWin",
                            competition=competition,
                            sport="football",
                            market=CANONICAL_OU_MARKET,
                            home_team=fields["home_team"],
                            away_team=fields["away_team"],
                            home_odds=over_odds,
                            draw_odds=0.0,
                            away_odds=under_odds,
                            start_time=start_time,
                            collected_at=collected,
                            feed_type="prematch",
                            line=line,
                        )
                    )
    return matches
