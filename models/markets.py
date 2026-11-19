"""Canonical market families for matching and arbitrage grouping.

Bookmakers emit different display labels for the same market
("Match Odds", "1X2", "Over/Under 2.5"). Arbitrage must group by
family + line, never by raw label, and must never mix 1X2 selections
with Over/Under selections.
"""

from __future__ import annotations

MARKET_1X2 = "1x2"
MARKET_OVER_UNDER = "over_under"
CANONICAL_OU_MARKET = "over_under"
TARGET_OU_LINE = 2.5

_1X2_COMPACT = {
    "1x2",
    "matchodds",
    "matchwinner",
    "fulltimeresult",
    "macsonucu",
    "result",
}

_OU_COMPACT = {
    "overunder",
    "over_under",
    "overunder25",
    "overunder2.5",
    "toplam",
    "toplamgol",
}


def normalize_market_name(market: str | None) -> str:
    return (market or "").strip().lower().replace("ç", "c")


def market_family(market: str | None) -> str:
    raw = normalize_market_name(market)
    compact = (
        raw.replace(" ", "")
        .replace("-", "")
        .replace("/", "")
        .replace("_", "")
    )
    if compact in _1X2_COMPACT:
        return MARKET_1X2
    if "over/under" in raw or compact in _OU_COMPACT or compact.startswith("overunder"):
        return MARKET_OVER_UNDER
    return compact or MARKET_1X2


def is_1x2_market(market: str | None) -> bool:
    return market_family(market) == MARKET_1X2


def is_over_under_market(market: str | None) -> bool:
    return market_family(market) == MARKET_OVER_UNDER


def line_key(match) -> float | None:
    line = getattr(match, "line", None)
    if line is None or line == "":
        return None
    try:
        return round(float(line), 2)
    except (TypeError, ValueError):
        return None


def arb_group_key(match) -> tuple:
    """Identity used to keep 1X2 and each O/U line in separate arb groups."""
    family = market_family(getattr(match, "market", None))
    if family == MARKET_OVER_UNDER:
        return (family, line_key(match))
    return (MARKET_1X2, None)


def parse_ou_line_from_name(market_name: str | None) -> float | None:
    """Extract a totals line from a catalogue name such as 'Over/Under 2.5'."""
    import re

    text = market_name or ""
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return round(float(match.group(1)), 2)
    except (TypeError, ValueError):
        return None
