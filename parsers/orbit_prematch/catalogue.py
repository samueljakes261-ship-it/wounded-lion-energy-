"""Normalize Orbit prematch catalogue rows for the frozen live parser.

Live OrbitParser requires catalogue['event']['homeTeam'] / awayTeam,
competition.name, eventType.name, marketStartTime, totalMatched, and
runners[]. Prematch sport/details rows sometimes omit homeTeam/awayTeam
and only provide event.name ('Home vs Away'). Filling those fields here
does not change parsers/orbit/parser.py.
"""

import re


_SPLITTERS = (
    re.compile(r"\s+vs\.?\s+", re.IGNORECASE),
    re.compile(r"\s+v\.?\s+", re.IGNORECASE),
    re.compile(r"\s+-\s+"),
)


def split_event_name(name):
    text = (name or "").strip()
    if not text:
        return None, None
    for splitter in _SPLITTERS:
        parts = splitter.split(text, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    return None, None


def _implied_ok(home, draw, away):
    """BACK 1X2 sanity check.

    Rejects placeholder ladders (1.10/1.10/1.10) and inverted books
    like 12/6.6/5.9. Thin prematch BACK books can sit a bit above 1.35
    overround; those are still real quotes.
    """
    try:
        prices = [float(home), float(draw), float(away)]
    except (TypeError, ValueError):
        return False
    if any(price <= 0 for price in prices):
        return False
    if all(1.01 <= price <= 1.15 for price in prices):
        return False
    implied = sum(1.0 / price for price in prices)
    return 0.90 <= implied <= 1.60


def normalize_prematch_market(market):
    if not isinstance(market, dict):
        return market
    event = dict(market.get("event") or {})
    home = event.get("homeTeam")
    away = event.get("awayTeam")
    if not home or not away:
        split_home, split_away = split_event_name(event.get("name") or "")
        if split_home and split_away:
            home = home or split_home
            away = away or split_away
    if (not home or not away) and isinstance(market.get("runners"), list):
        named = [
            (runner.get("runnerName") or "").strip()
            for runner in market["runners"]
            if (runner.get("runnerName") or "").strip().lower() not in {"draw", "the draw"}
        ]
        if len(named) >= 2:
            home = home or named[0]
            away = away or named[1]
    event["homeTeam"] = home
    event["awayTeam"] = away
    if "id" not in event and market.get("eventId"):
        event["id"] = market.get("eventId")
    market = dict(market)
    market["event"] = event
    competition = market.get("competition")
    if not isinstance(competition, dict):
        market["competition"] = {"name": market.get("competitionName") or "Unknown"}
    elif "name" not in competition:
        competition = dict(competition)
        competition["name"] = competition.get("competitionName") or "Unknown"
        market["competition"] = competition
    event_type = market.get("eventType")
    if not isinstance(event_type, dict):
        market["eventType"] = {"name": "Soccer"}
    elif "name" not in event_type:
        event_type = dict(event_type)
        event_type["name"] = "Soccer"
        market["eventType"] = event_type
    market.setdefault("marketStartTime", event.get("openDate") or 0)
    market.setdefault("totalMatched", 0)
    return market
