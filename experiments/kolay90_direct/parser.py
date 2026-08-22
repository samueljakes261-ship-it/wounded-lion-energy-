"""Isolated kolay90 football prematch 1X2 parser.

Does not import or modify parsers/kolay90_parser.py or models.match.
Only football prematch Match Result (1 / 0 / 2) is accepted.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from models import ExperimentMatchOdds

BOOKMAKER = "kolay90"
SPORT = "football"
FEED = "prematch"

# Explicit name fields only. type=1 is NOT assumed to mean football.
SPORT_KEYS = ("spor", "sport", "brans", "dal", "sport_name", "sportName", "sportId")
FOOTBALL_NAMES = {"futbol", "football", "soccer"}

# Live / non-prematch markers. Presence rejects the event.
LIVE_KEYS = ("skor", "score", "canli", "live", "ms", "dakika", "minute")
LIVE_STATUSES = {"live", "canli", "inplay", "in_play", "playing"}


def unwrap_events(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if payload.get("hata") is True:
        return []
    for key in ("maclar", "matches", "data", "result", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    # Some responses are a dict of id -> event.
    if payload and all(isinstance(v, dict) for v in payload.values()):
        sample = next(iter(payload.values()))
        if "ev_sahibi" in sample or "oranlar" in sample:
            return [v for v in payload.values() if isinstance(v, dict)]
    return []


def inspect_payload(payload: Any) -> dict:
    events = unwrap_events(payload)
    key_counts: Counter[str] = Counter()
    type_values: Counter[str] = Counter()
    sport_values: Counter[str] = Counter()
    for item in events:
        key_counts.update(item.keys())
        if "type" in item:
            type_values[str(item.get("type"))] += 1
        for key in SPORT_KEYS:
            if key in item and item.get(key) is not None:
                sport_values[f"{key}={item.get(key)}"] += 1
    return {
        "event_count": len(events),
        "wrapper_hata": bool(isinstance(payload, dict) and payload.get("hata") is True),
        "top_level_type": type(payload).__name__,
        "top_level_keys": list(payload.keys())[:40] if isinstance(payload, dict) else None,
        "field_counts": dict(key_counts.most_common(40)),
        "type_values": dict(type_values),
        "sport_field_values": dict(sport_values),
        "football_discriminator": _describe_football_discriminator(events, sport_values),
    }


def _describe_football_discriminator(events: list[dict], sport_values: Counter[str]) -> str:
    if sport_values:
        return "explicit sport-name field present; football requires a futbol/football/soccer value"
    if not events:
        return "no events to inspect"
    return (
        "no spor/sport/brans field observed; football is ambiguous and events "
        "are rejected until a discriminator is confirmed"
    )


def _sport_label(item: dict) -> str | None:
    for key in SPORT_KEYS:
        value = item.get(key)
        if value is None:
            continue
        return str(value).strip().lower()
    return None


def is_football(item: dict) -> bool:
    label = _sport_label(item)
    if label is None:
        return False
    return label in FOOTBALL_NAMES


def is_prematch(item: dict) -> bool:
    status = str(item.get("durum") or item.get("status") or "").strip().lower()
    if status in LIVE_STATUSES:
        return False
    for key in LIVE_KEYS:
        if item.get(key) not in (None, "", 0, "0"):
            # skor="0-0" would reject kickoff fixtures; only reject structured live clocks.
            if key in ("dakika", "minute") and item.get(key) not in (None, "", 0, "0"):
                return False
            if key in ("canli", "live") and bool(item.get(key)):
                return False
    start = _start_time(item)
    if start is None:
        return False
    return start.tzinfo is not None


def _start_time(item: dict) -> datetime | None:
    zaman = item.get("zaman")
    sec = None
    if isinstance(zaman, dict):
        sec = zaman.get("sec")
    elif isinstance(zaman, (int, float)):
        sec = zaman
    if sec is None:
        return None
    try:
        value = float(sec)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value = value / 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc)


def extract_1x2(item: dict) -> tuple[str, str, str] | None:
    oranlar = item.get("oranlar")
    if not isinstance(oranlar, dict):
        return None
    if not all(key in oranlar for key in ("1", "0", "2")):
        return None
    home, draw, away = oranlar["1"], oranlar["0"], oranlar["2"]
    if home in (None, "") or draw in (None, "") or away in (None, ""):
        return None
    return str(home), str(draw), str(away)


def parse_event(item: dict, collected_at: datetime | None = None) -> ExperimentMatchOdds | None:
    if not is_football(item):
        return None
    if not is_prematch(item):
        return None
    raw = extract_1x2(item)
    if raw is None:
        return None
    raw_home, raw_draw, raw_away = raw
    try:
        home = float(raw_home)
        draw = float(raw_draw)
        away = float(raw_away)
    except (TypeError, ValueError):
        return None
    home_team = item.get("ev_sahibi")
    away_team = item.get("deplasman")
    if not home_team or not away_team:
        return None
    start = _start_time(item)
    if start is None:
        return None
    event_id = str(item.get("_id") or item.get("code") or f"{home_team}:{away_team}:{int(start.timestamp())}")
    return ExperimentMatchOdds(
        bookmaker=BOOKMAKER,
        event_id=event_id,
        home_team=str(home_team),
        away_team=str(away_team),
        start_time=start,
        feed_type=FEED,
        sport=SPORT,
        home_back=home,
        draw_back=draw,
        away_back=away,
        collected_at=collected_at or datetime.now(timezone.utc),
        competition=str(item.get("lig_id")) if item.get("lig_id") is not None else None,
        raw_home=raw_home,
        raw_draw=raw_draw,
        raw_away=raw_away,
    )


def parse_payload(payload: Any, collected_at: datetime | None = None) -> list[ExperimentMatchOdds]:
    return [
        parsed
        for item in unwrap_events(payload)
        if (parsed := parse_event(item, collected_at)) is not None
    ]


def validate_against_raw(item: dict, parsed: ExperimentMatchOdds) -> list[str]:
    raw = extract_1x2(item)
    if raw is None:
        return ["missing raw 1X2"]
    failures = []
    mapping = (
        ("HOME", raw[0], parsed.home_back),
        ("DRAW", raw[1], parsed.draw_back),
        ("AWAY", raw[2], parsed.away_back),
    )
    for label, raw_value, parsed_value in mapping:
        try:
            expected = float(raw_value)
        except (TypeError, ValueError):
            failures.append(f"{label} raw {raw_value!r} is not a float")
            continue
        if parsed_value != expected:
            failures.append(
                f"{label} raw={raw_value!r} parsed={parsed_value!r} expected={expected!r}"
            )
    return failures
