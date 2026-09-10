"""Decimal-odds validation for Kenyan bookmaker payloads.

Rejects values that are not implementable prices: zero, negative, NaN,
IDs accidentally parsed as odds, and other impossible magnitudes.
Kept here so parsers and the Kenyan engine share one rule.
"""

MIN_DECIMAL_ODDS = 1.01
MAX_DECIMAL_ODDS = 1000.0


def parse_decimal_odds(value):
    """Return a float in [MIN_DECIMAL_ODDS, MAX_DECIMAL_ODDS] or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price != price or price in (float("inf"), float("-inf")):
        return None
    if price < MIN_DECIMAL_ODDS or price > MAX_DECIMAL_ODDS:
        return None
    return price


def is_valid_decimal_odds(value) -> bool:
    return parse_decimal_odds(value) is not None


def triple_is_valid(home_odds, draw_odds, away_odds) -> bool:
    return (
        is_valid_decimal_odds(home_odds)
        and is_valid_decimal_odds(draw_odds)
        and is_valid_decimal_odds(away_odds)
    )
