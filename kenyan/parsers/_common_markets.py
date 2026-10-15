"""1xCorp two-way winner and totals extraction for 1xBet / 22Bet.

Football 1X2 stays in `_common_1x2.py`. This module only reads:

- group 1 types 1+3 (two-way match winner, no fabricated draw)
- group 101 types 401+402 (basketball moneyline)
- group 17 types 9+10 (match totals, line from parameter/P)

Team totals (groups 15/62) and handicaps (group 2) are ignored.
"""
from kenyan.odds import parse_decimal_odds

TWO_WAY_WINNER_GROUP_ID = 1
TWO_WAY_HOME_TYPE = 1
TWO_WAY_AWAY_TYPE = 3

BASKETBALL_MONEYLINE_GROUP_ID = 101
BASKETBALL_HOME_TYPE = 401
BASKETBALL_AWAY_TYPE = 402

TOTAL_GROUP_ID = 17
TOTAL_OVER_TYPE = 9
TOTAL_UNDER_TYPE = 10


def _line_value(item):
    for key in ("parameter", "P", "param", "p"):
        if key in item and item.get(key) not in (None, ""):
            try:
                return round(float(item.get(key)), 2)
            except (TypeError, ValueError):
                return None
    return None


def _grouped_items(group):
    items = []
    for wrapper in group.get("events") or []:
        if not isinstance(wrapper, list):
            continue
        for item in wrapper:
            if isinstance(item, dict):
                items.append(item)
    return items


def _price_grouped(item):
    if item.get("blocked"):
        return None
    return parse_decimal_odds(item.get("cf"))


def _price_flat(item):
    if item.get("B"):
        return None
    return parse_decimal_odds(item.get("C"))


def extract_two_way_winner_from_event_groups(
    event_groups,
    *,
    group_id=TWO_WAY_WINNER_GROUP_ID,
    home_type=TWO_WAY_HOME_TYPE,
    away_type=TWO_WAY_AWAY_TYPE,
):
    """First complete two-way winner cluster. Empty dict if none."""
    if not isinstance(event_groups, list):
        return {}
    for group in event_groups:
        if not isinstance(group, dict) or group.get("groupId") != group_id:
            continue
        home = away = None
        for item in _grouped_items(group):
            outcome_type = item.get("type")
            price = _price_grouped(item)
            if price is None:
                continue
            if outcome_type == home_type and home is None:
                home = price
            elif outcome_type == away_type and away is None:
                away = price
        if home is not None and away is not None:
            return {
                "home": home,
                "away": away,
                "cluster_id": f"g{group_id}:c0",
                "market_id": str(group_id),
            }
    return {}


def extract_two_way_winner_from_flat_events(
    events,
    *,
    group_id=TWO_WAY_WINNER_GROUP_ID,
    home_type=TWO_WAY_HOME_TYPE,
    away_type=TWO_WAY_AWAY_TYPE,
):
    if not isinstance(events, list):
        return {}
    home = away = None
    for item in events:
        if not isinstance(item, dict) or item.get("G") != group_id:
            continue
        price = _price_flat(item)
        if price is None:
            continue
        outcome_type = item.get("T")
        if outcome_type == home_type and home is None:
            home = price
        elif outcome_type == away_type and away is None:
            away = price
    if home is not None and away is not None:
        return {
            "home": home,
            "away": away,
            "cluster_id": f"g{group_id}:c0",
            "market_id": str(group_id),
        }
    return {}


def extract_totals_from_event_groups(event_groups, *, group_id=TOTAL_GROUP_ID):
    """One record per distinct total line in group 17."""
    if not isinstance(event_groups, list):
        return []
    for group in event_groups:
        if not isinstance(group, dict) or group.get("groupId") != group_id:
            continue
        by_line = {}
        for item in _grouped_items(group):
            line = _line_value(item)
            if line is None:
                continue
            price = _price_grouped(item)
            if price is None:
                continue
            slot = by_line.setdefault(line, {})
            outcome_type = item.get("type")
            if outcome_type == TOTAL_OVER_TYPE and "over" not in slot:
                slot["over"] = price
            elif outcome_type == TOTAL_UNDER_TYPE and "under" not in slot:
                slot["under"] = price
        results = []
        for index, (line, prices) in enumerate(sorted(by_line.items())):
            if "over" not in prices or "under" not in prices:
                continue
            results.append(
                {
                    "line": line,
                    "over": prices["over"],
                    "under": prices["under"],
                    "cluster_id": f"g{group_id}:l{line}:c{index}",
                    "market_id": f"{group_id}:{line}",
                }
            )
        return results
    return []


def extract_totals_from_flat_events(events, *, group_id=TOTAL_GROUP_ID):
    if not isinstance(events, list):
        return []
    by_line = {}
    for item in events:
        if not isinstance(item, dict) or item.get("G") != group_id:
            continue
        line = _line_value(item)
        if line is None:
            continue
        price = _price_flat(item)
        if price is None:
            continue
        slot = by_line.setdefault(line, {})
        outcome_type = item.get("T")
        if outcome_type == TOTAL_OVER_TYPE and "over" not in slot:
            slot["over"] = price
        elif outcome_type == TOTAL_UNDER_TYPE and "under" not in slot:
            slot["under"] = price
    results = []
    for index, (line, prices) in enumerate(sorted(by_line.items())):
        if "over" not in prices or "under" not in prices:
            continue
        results.append(
            {
                "line": line,
                "over": prices["over"],
                "under": prices["under"],
                "cluster_id": f"g{group_id}:l{line}:c{index}",
                "market_id": f"{group_id}:{line}",
            }
        )
    return results
