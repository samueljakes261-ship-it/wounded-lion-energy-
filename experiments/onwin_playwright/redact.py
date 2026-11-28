"""Summaries of Onwin traffic that keep tokens and cookies out of logs."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

SECRET_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-message-metadata",
    "x-token",
}


def _secret_header(name: str) -> bool:
    lowered = name.lower()
    if lowered in SECRET_HEADER_NAMES:
        return True
    return "token" in lowered or "cookie" in lowered or "authorization" in lowered


def fingerprint(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def header_summary(headers: dict) -> dict:
    """Record header names. Secret values become presence, length, and a short hash."""
    summary = {}
    for key, value in headers.items():
        name = str(key).lower()
        text = "" if value is None else str(value)
        if _secret_header(name):
            summary[name] = {
                "present": bool(text),
                "length": len(text),
                "fingerprint": fingerprint(text),
            }
        else:
            summary[name] = text[:160]
    return summary


def safe_endpoint(url: str) -> dict:
    parts = urlsplit(url or "")
    return {
        "scheme": parts.scheme,
        "host": parts.hostname or "",
        "path": parts.path or "",
        "has_query": bool(parts.query),
    }


def post_summary(post_data: str | None) -> dict:
    if not post_data:
        return {"present": False}
    summary = {
        "present": True,
        "bytes": len(post_data.encode("utf-8", errors="replace")),
    }
    try:
        parsed = json.loads(post_data)
    except json.JSONDecodeError:
        summary["json"] = False
        return summary
    summary["json"] = True
    if isinstance(parsed, dict):
        summary["keys"] = list(parsed)[:40]
    elif isinstance(parsed, list):
        summary["keys"] = "array"
        summary["items"] = len(parsed)
    return summary


def count_payload(data) -> dict:
    """Count events, markets, and priced outcomes in a main-line sports tree."""
    if not isinstance(data, dict):
        return {
            "shape": type(data).__name__,
            "events": 0,
            "markets": 0,
            "odds": 0,
            "event_ids": [],
        }
    events = 0
    markets = 0
    odds = 0
    event_ids = []
    sports = data.get("sports") or {}
    if not isinstance(sports, dict):
        return {
            "shape": "not_sports_tree",
            "events": 0,
            "markets": 0,
            "odds": 0,
            "event_ids": [],
        }
    for sport in sports.values():
        if not isinstance(sport, dict):
            continue
        categories = sport.get("categories") or {}
        if not isinstance(categories, dict):
            continue
        for category in categories.values():
            if not isinstance(category, dict):
                continue
            tournaments = category.get("tournaments") or {}
            if not isinstance(tournaments, dict):
                continue
            for tournament in tournaments.values():
                if not isinstance(tournament, dict):
                    continue
                event_map = tournament.get("events") or {}
                if not isinstance(event_map, dict):
                    continue
                for event_id, event in event_map.items():
                    events += 1
                    event_ids.append(str(event_id))
                    if not isinstance(event, dict):
                        continue
                    scopes = event.get("scopes") or {}
                    if not isinstance(scopes, dict):
                        continue
                    for scope in scopes.values():
                        if not isinstance(scope, dict):
                            continue
                        market_map = scope.get("markets") or {}
                        if not isinstance(market_map, dict):
                            continue
                        for market in market_map.values():
                            markets += 1
                            if not isinstance(market, dict):
                                continue
                            outcomes = market.get("outcomes") or {}
                            if not isinstance(outcomes, dict):
                                continue
                            for outcome in outcomes.values():
                                if isinstance(outcome, dict) and outcome.get("coefficient") is not None:
                                    odds += 1
    return {
        "shape": "sports_tree",
        "events": events,
        "markets": markets,
        "odds": odds,
        "event_ids": event_ids,
    }
