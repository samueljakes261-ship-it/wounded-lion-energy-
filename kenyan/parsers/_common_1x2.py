"""
Shared "type-numbered 1X2" extraction logic for 1xBet and 22Bet.

Both bookmakers are built on the same underlying odds-provider
platform (1xCorp/Melbet family) and use the SAME numeric market/outcome
convention, confirmed by live inspection (see kenyan/README-style notes
in onexbet_parser.py / bet22_parser.py):

    outcome type 1 = HOME
    outcome type 2 = DRAW
    outcome type 3 = AWAY
    group id 1     = the main full-match 1X2 market

Two different payload shapes were observed carrying this same
convention:

  1. "flat" shape -- a single `E` (or nested `AE`) list of
     `{"T": <type>, "C": <price>, "G": <group>, "B": <blocked?>}` dicts.
     Seen on: 1xBet prematch, 22Bet live, 22Bet prematch.

  2. "grouped" shape -- an `eventGroups` list of
     `{"groupId": <group>, "events": [[{...}], [{...}], [{...}]]}`,
     where each of the 3 inner single-item lists holds one outcome.
     Seen on: 1xBet live.

This module normalizes both into a single `{outcome_type: price}` dict
so the two parsers never have to duplicate the shape-detection logic.
"""
from typing import Optional


def extract_1x2_from_flat_events(events: Optional[list]) -> dict:
    """
    `events` is the raw `E` (or `AE[*].ME`) list. Returns
    {1: home_price, 2: draw_price, 3: away_price} for whichever of the
    three outcomes are present, unblocked, and have a positive price.
    Missing/blocked/invalid outcomes are simply absent from the result
    -- callers decide whether a partial result counts as "incomplete".
    """

    result = {}

    if not isinstance(events, list):
        return result

    for item in events:
        if not isinstance(item, dict):
            continue

        outcome_type = item.get("T")
        group = item.get("G")

        if group != 1 or outcome_type not in (1, 2, 3):
            continue

        if item.get("B"):  # blocked/unavailable odds
            continue

        price = item.get("C")

        try:
            price = float(price)
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        result[outcome_type] = price

    return result


def extract_1x2_from_event_groups(event_groups: Optional[list]) -> dict:
    """
    `event_groups` is the raw `eventGroups` list (the "grouped" shape).
    Same return contract as `extract_1x2_from_flat_events`.
    """

    result = {}

    if not isinstance(event_groups, list):
        return result

    for group in event_groups:
        if not isinstance(group, dict) or group.get("groupId") != 1:
            continue

        for outcome_wrapper in group.get("events") or []:
            if not isinstance(outcome_wrapper, list):
                continue

            for item in outcome_wrapper:
                if not isinstance(item, dict):
                    continue

                outcome_type = item.get("type")

                if outcome_type not in (1, 2, 3):
                    continue

                if item.get("blocked"):
                    continue

                price = item.get("cf")

                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue

                if price <= 0:
                    continue

                result[outcome_type] = price

        # Only one groupId == 1 is expected per event; stop once found.
        if result:
            break

    return result


def is_complete_1x2(prices: dict) -> bool:
    return all(outcome in prices for outcome in (1, 2, 3))
