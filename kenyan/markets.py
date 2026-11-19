"""Canonical Kenyan market identity.

Kept inside kenyan/ so Turkish `models.markets.arb_group_key` (which
does not include period, and pins Over/Under to line 2.5 in
engine/over_under.py) is never changed.

A market match requires the same sport, market type, period, line, and
outcome family. Football 1X2 continues to key as MATCH_WINNER /
FULL_MATCH / no line.
"""
from __future__ import annotations

SPORT_FOOTBALL = "football"
SPORT_TENNIS = "tennis"
SPORT_BASKETBALL = "basketball"
SPORT_VOLLEYBALL = "volleyball"

MARKET_MATCH_WINNER = "MATCH_WINNER"
MARKET_TOTAL = "TOTAL"

PERIOD_FULL_MATCH = "FULL_MATCH"
PERIOD_SET_1 = "SET_1"
PERIOD_SET_2 = "SET_2"
PERIOD_SET_3 = "SET_3"
PERIOD_SET_4 = "SET_4"
PERIOD_SET_5 = "SET_5"
PERIOD_Q1 = "Q1"
PERIOD_Q2 = "Q2"
PERIOD_Q3 = "Q3"
PERIOD_Q4 = "Q4"
PERIOD_H1 = "H1"
PERIOD_H2 = "H2"

FAMILY_WINNER = "winner"
FAMILY_TOTAL = "total"

OUTCOME_HOME = "HOME"
OUTCOME_DRAW = "DRAW"
OUTCOME_AWAY = "AWAY"
OUTCOME_PLAYER_1 = "PLAYER_1"
OUTCOME_PLAYER_2 = "PLAYER_2"
OUTCOME_OVER = "OVER"
OUTCOME_UNDER = "UNDER"

_SPORT_ALIASES = {
    "soccer": SPORT_FOOTBALL,
    "football": SPORT_FOOTBALL,
    "tennis": SPORT_TENNIS,
    "basketball": SPORT_BASKETBALL,
    "volleyball": SPORT_VOLLEYBALL,
}

_PERIOD_ALIASES = {
    "": PERIOD_FULL_MATCH,
    "game": PERIOD_FULL_MATCH,
    "match": PERIOD_FULL_MATCH,
    "full time": PERIOD_FULL_MATCH,
    "fulltime": PERIOD_FULL_MATCH,
    "full match": PERIOD_FULL_MATCH,
    "1st set": PERIOD_SET_1,
    "set 1": PERIOD_SET_1,
    "set1": PERIOD_SET_1,
    "2nd set": PERIOD_SET_2,
    "set 2": PERIOD_SET_2,
    "set2": PERIOD_SET_2,
    "3rd set": PERIOD_SET_3,
    "set 3": PERIOD_SET_3,
    "set3": PERIOD_SET_3,
    "4th set": PERIOD_SET_4,
    "set 4": PERIOD_SET_4,
    "set4": PERIOD_SET_4,
    "5th set": PERIOD_SET_5,
    "set 5": PERIOD_SET_5,
    "set5": PERIOD_SET_5,
    "1st quarter": PERIOD_Q1,
    "quarter 1": PERIOD_Q1,
    "q1": PERIOD_Q1,
    "2nd quarter": PERIOD_Q2,
    "quarter 2": PERIOD_Q2,
    "q2": PERIOD_Q2,
    "3rd quarter": PERIOD_Q3,
    "quarter 3": PERIOD_Q3,
    "q3": PERIOD_Q3,
    "4th quarter": PERIOD_Q4,
    "quarter 4": PERIOD_Q4,
    "q4": PERIOD_Q4,
    "1st half": PERIOD_H1,
    "first half": PERIOD_H1,
    "h1": PERIOD_H1,
    "2nd half": PERIOD_H2,
    "second half": PERIOD_H2,
    "h2": PERIOD_H2,
}

_TOTAL_NOUN = {
    SPORT_FOOTBALL: "Total Goals",
    SPORT_TENNIS: "Total Games",
    SPORT_BASKETBALL: "Total Points",
    SPORT_VOLLEYBALL: "Total Points",
}

_PERIOD_LABEL = {
    PERIOD_FULL_MATCH: "",
    PERIOD_SET_1: "Set 1",
    PERIOD_SET_2: "Set 2",
    PERIOD_SET_3: "Set 3",
    PERIOD_SET_4: "Set 4",
    PERIOD_SET_5: "Set 5",
    PERIOD_Q1: "Q1",
    PERIOD_Q2: "Q2",
    PERIOD_Q3: "Q3",
    PERIOD_Q4: "Q4",
    PERIOD_H1: "1st Half",
    PERIOD_H2: "2nd Half",
}

_SPORT_DISPLAY = {
    SPORT_FOOTBALL: "Football",
    SPORT_TENNIS: "Tennis",
    SPORT_BASKETBALL: "Basketball",
    SPORT_VOLLEYBALL: "Volleyball",
}


def sport_key(value) -> str:
    if not isinstance(value, str):
        value = getattr(value, "sport", None) or ""
    return _SPORT_ALIASES.get((value or "").strip().lower(), (value or "").strip().lower())


def sport_display(value) -> str:
    key = sport_key(value)
    return _SPORT_DISPLAY.get(key, (key or "Unknown").title())


def normalize_period(value) -> str | None:
    if value is None:
        return PERIOD_FULL_MATCH
    text = str(value).strip().lower()
    if text in _PERIOD_ALIASES:
        return _PERIOD_ALIASES[text]
    compact = text.replace("-", " ")
    if compact in _PERIOD_ALIASES:
        return _PERIOD_ALIASES[compact]
    return None


def line_key(match) -> float | None:
    line = getattr(match, "line", None)
    if line is None or line == "":
        return None
    try:
        return round(float(line), 2)
    except (TypeError, ValueError):
        return None


def infer_market_type(match) -> str:
    explicit = (getattr(match, "market_type", None) or "").strip()
    if explicit:
        return explicit
    raw = (getattr(match, "market", None) or "").strip().lower()
    compact = raw.replace(" ", "").replace("-", "").replace("/", "").replace("_", "")
    if compact in {"1x2", "matchodds", "matchwinner", "fulltimeresult", "winner"}:
        return MARKET_MATCH_WINNER
    if "over" in raw or "under" in raw or compact.startswith("total"):
        return MARKET_TOTAL
    return MARKET_MATCH_WINNER


def infer_period(match) -> str:
    explicit = getattr(match, "period", None)
    if explicit:
        mapped = normalize_period(explicit) if explicit != PERIOD_FULL_MATCH else PERIOD_FULL_MATCH
        if mapped:
            return mapped
        if explicit in _PERIOD_LABEL:
            return explicit
    return PERIOD_FULL_MATCH


def infer_family(match) -> str:
    explicit = (getattr(match, "outcome_family", None) or "").strip()
    if explicit:
        return explicit
    if infer_market_type(match) == MARKET_TOTAL:
        return FAMILY_TOTAL
    return FAMILY_WINNER


def outcome_arity(match) -> int:
    """3 when a real draw price exists; otherwise 2. Never invents a draw."""
    from kenyan.odds import is_valid_decimal_odds

    draw = getattr(match, "draw_odds", None)
    if draw is not None and is_valid_decimal_odds(draw):
        return 3
    return 2


def kenyan_market_key(match) -> tuple:
    """Identity used to keep incompatible Kenyan markets from matching."""
    family = infer_family(match)
    market_type = infer_market_type(match)
    period = infer_period(match)
    line = line_key(match) if family == FAMILY_TOTAL else None
    return (sport_key(match), market_type, period, line, family, outcome_arity(match))


def format_line(line) -> str:
    try:
        value = float(line)
    except (TypeError, ValueError):
        return str(line)
    if value == int(value):
        return str(int(value))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def market_label(match) -> str:
    explicit = (getattr(match, "market_label", None) or "").strip()
    if explicit:
        return explicit
    sport = sport_display(match)
    market_type = infer_market_type(match)
    period = infer_period(match)
    period_text = _PERIOD_LABEL.get(period, "")
    if market_type == MARKET_TOTAL:
        noun = _TOTAL_NOUN.get(sport_key(match), "Total")
        line = line_key(match)
        line_text = format_line(line) if line is not None else ""
        if period != PERIOD_FULL_MATCH and period_text:
            noun = f"{period_text} {noun}"
        if line_text:
            return f"{sport} • {noun} • {line_text}"
        return f"{sport} • {noun}"
    return f"{sport} • Match Winner"


def winner_outcome_labels(match) -> tuple[str, str]:
    if sport_key(match) == SPORT_TENNIS:
        return OUTCOME_PLAYER_1, OUTCOME_PLAYER_2
    return OUTCOME_HOME, OUTCOME_AWAY


def finalize_match(match):
    """Fill canonical fields when parsers left them blank."""
    if not getattr(match, "market_type", None):
        match.market_type = infer_market_type(match)
    if not getattr(match, "period", None):
        match.period = PERIOD_FULL_MATCH
    else:
        mapped = normalize_period(match.period)
        if mapped:
            match.period = mapped
    if not getattr(match, "outcome_family", None):
        match.outcome_family = infer_family(match)
    if not getattr(match, "market_label", None):
        match.market_label = market_label(match)
    return match
