"""BetKanyon prematch 1X2 parser.

Separate from parsers.betkanyon.parser (live, frozen). Walks the
decrypted JSON wherever events sit -- it does not assume the live
CNT/CL/E + StakeTypes.Id==1 + Stakes.SN/F layout is the only shape.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

MIN_ODDS = 1.01
MAX_ODDS = 100.0
# A real 1X2 book (or exchange BACK book) has overround around 1.0-1.3.
# Sum of implied probabilities like 0.40 means the three F values are
# not match-result prices.
MIN_IMPLIED = 0.95
MAX_IMPLIED = 1.35

HOME_TOKENS = {"1", "home", "ev sahibi", "evsahibi", "kazanan1"}
DRAW_TOKENS = {"x", "draw", "beraberlik", "berabere"}
AWAY_TOKENS = {"2", "away", "deplasman", "kazanan2"}
MATCH_ODDS_NAMES = {
    "maç sonucu",
    "mac sonucu",
    "match odds",
    "match winner",
    "1x2",
    "full time result",
}
OU_MARKET_IDS = {3, -3, "3", "-3"}
OU_OVER_TOKENS = {"üst", "ust", "over"}
OU_UNDER_TOKENS = {"alt", "under"}
TARGET_OU_LINE = 2.5
MIN_OU_IMPLIED = 0.80
MAX_OU_IMPLIED = 1.30


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm(value: Any) -> str:
    return _text(value).lower().replace("ç", "c")


def _plausible_odds(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", ".")
        if not value:
            return None
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds != odds or odds in (float("inf"), float("-inf")):
        return None
    if MIN_ODDS <= odds <= MAX_ODDS:
        return odds
    return None


def _looks_like_event(node: dict) -> bool:
    home = node.get("EHT") or node.get("HT") or node.get("home")
    away = node.get("EAT") or node.get("AT") or node.get("away")
    has_teams = bool(_text(home) and _text(away))
    has_markets = any(
        key in node
        for key in ("StakeTypes", "stakeTypes", "Stakes", "stakes", "Markets", "markets")
    )
    return has_teams and (has_markets or "Id" in node or "D" in node)


def _iter_events(node: Any):
    if isinstance(node, dict):
        if _looks_like_event(node):
            yield node
        for value in node.values():
            yield from _iter_events(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_events(item)


def _market_lists(event: dict) -> list:
    for key in ("StakeTypes", "stakeTypes", "Markets", "markets"):
        value = event.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def _stake_lists(market: dict) -> list:
    for key in ("Stakes", "stakes", "Outcomes", "outcomes", "Selections", "selections"):
        value = market.get(key)
        if isinstance(value, list) and value:
            return value
    if _selection_token(market) and _stake_price(market) is not None:
        return [market]
    return []


def _is_match_odds_market(market: dict) -> bool:
    # Id == 1 is BetKanyon's stable "Match Result"/1X2 market identifier
    # -- the same rule the proven live parser
    # (parsers/betkanyon/parser.py) trusts with no name check at all.
    # The market's display name ("N") is locale-dependent (e.g. Turkish
    # "Maç Sonucu" vs English "Result" depending on langId) and must
    # never be required to recognize the market; a name match is only
    # a fallback for payloads where Id itself is missing/renamed.
    market_id = market.get("Id", market.get("id", market.get("SID")))
    if market_id in (1, "1", 1.0):
        return True
    name = _norm(
        market.get("N")
        or market.get("EN")
        or market.get("EGN")
        or market.get("name")
        or market.get("GN")
    )
    if name in MATCH_ODDS_NAMES:
        return True
    return False


def _selection_token(stake: dict) -> str:
    return _norm(stake.get("SN") or stake.get("N") or stake.get("code") or stake.get("selection"))


def _selection_side(stake: dict) -> Optional[str]:
    token = _selection_token(stake)
    if token in HOME_TOKENS:
        return "home"
    if token in DRAW_TOKENS:
        return "draw"
    if token in AWAY_TOKENS:
        return "away"
    # Live BetKanyon selection codes: 1=home, 2=draw, 3=away.
    # Prematch rows may omit SN and only carry SC.
    sc = stake.get("SC", stake.get("sc"))
    if sc in (1, "1", 1.0):
        return "home"
    if sc in (2, "2", 2.0):
        return "draw"
    if sc in (3, "3", 3.0):
        return "away"
    return None


def _stake_locked(stake: dict) -> bool:
    if stake.get("IsL") is True or stake.get("isLocked") is True:
        return True
    if stake.get("IsA") is False or stake.get("isActive") is False:
        return True
    return False


def _stake_price(stake: dict) -> Optional[float]:
    # Prematch 1X2 decimal price is Stake.F. Do not fall back to
    # identifiers or unrelated numeric fields.
    return _plausible_odds(stake.get("F"))


def _extract_1x2(event: dict) -> Optional[Tuple[float, float, float]]:
    home = draw = away = None
    markets = _market_lists(event)
    if not markets and isinstance(event.get("Stakes"), list):
        markets = [event]
    for market in markets:
        if not isinstance(market, dict):
            continue
        treating_event_as_market = market is event
        if not treating_event_as_market and not _is_match_odds_market(market):
            continue
        for stake in _stake_lists(market):
            if not isinstance(stake, dict):
                continue
            price = _stake_price(stake)
            if price is None:
                continue
            side = _selection_side(stake)
            if side == "home":
                home = price
            elif side == "draw":
                draw = price
            elif side == "away":
                away = price
        if home is not None and draw is not None and away is not None:
            implied = (1.0 / home) + (1.0 / draw) + (1.0 / away)
            if MIN_IMPLIED <= implied <= MAX_IMPLIED:
                return home, draw, away
            print(
                "[PREMATCH][BETKANYON][REJECT] "
                f"event={event.get('EHT') or event.get('HT')} vs "
                f"{event.get('EAT') or event.get('AT')} "
                f"market={market.get('Id')}/{market.get('N')} "
                f"outcome=1X2 reason=implied_sum={implied:.4f} "
                f"not a 1X2 book (HOME={home} DRAW={draw} AWAY={away})"
            )
        home = draw = away = None
    return None


def _is_totals_market(market: dict) -> bool:
    market_id = market.get("Id", market.get("id", market.get("SID")))
    if market_id in OU_MARKET_IDS:
        return True
    name = _norm(
        market.get("N")
        or market.get("EN")
        or market.get("EGN")
        or market.get("name")
        or market.get("GN")
    )
    return name in {"toplam", "toplam gol"}


def _ou_side(stake: dict) -> str | None:
    token = _selection_token(stake)
    if token in OU_OVER_TOKENS:
        return "over"
    if token in OU_UNDER_TOKENS:
        return "under"
    return None


def _extract_over_under(event: dict) -> dict:
    """Return {line: (over_odds, under_odds)} for complete totals lines."""
    by_line: dict = {}
    markets = _market_lists(event)
    for market in markets:
        if not isinstance(market, dict) or not _is_totals_market(market):
            continue
        for stake in _stake_lists(market):
            if not isinstance(stake, dict) or _stake_locked(stake):
                continue
            price = _stake_price(stake)
            if price is None:
                continue
            line_raw = stake.get("A")
            if line_raw is None:
                continue
            try:
                line = round(float(line_raw), 2)
            except (TypeError, ValueError):
                continue
            side = _ou_side(stake)
            if side is None:
                continue
            bucket = by_line.setdefault(line, {"over": None, "under": None})
            bucket[side] = price
    complete = {}
    for line, prices in by_line.items():
        over = prices.get("over")
        under = prices.get("under")
        if over is None or under is None:
            continue
        implied = (1.0 / over) + (1.0 / under)
        if MIN_OU_IMPLIED <= implied <= MAX_OU_IMPLIED:
            complete[line] = (over, under)
    return complete


def parse_prematch(data) -> Tuple[List[dict], Dict[str, int]]:
    """Return (events, stats) from one decrypted tournament payload."""
    stats = {
        "events_discovered": 0,
        "match_odds_markets": 0,
        "complete_1x2": 0,
        "over_under_markets": 0,
        "complete_ou_2_5": 0,
        "skipped_locked_or_incomplete": 0,
        "skipped_invalid_odds": 0,
    }
    parsed = []
    if data is None:
        return parsed, stats

    sport = "Football"
    if isinstance(data, dict):
        sport = data.get("EGN") or data.get("N") or sport

    seen = set()
    for event in _iter_events(data):
        event_id = event.get("Id") or event.get("EN")
        key = event_id or id(event)
        if key in seen:
            continue
        seen.add(key)

        home = _text(event.get("EHT") or event.get("HT") or event.get("home"))
        away = _text(event.get("EAT") or event.get("AT") or event.get("away"))
        if not home or not away:
            continue
        stats["events_discovered"] += 1

        markets = _market_lists(event)
        if any(_is_match_odds_market(m) for m in markets if isinstance(m, dict)):
            stats["match_odds_markets"] += 1

        prices = _extract_1x2(event)
        if prices is None:
            stats["skipped_locked_or_incomplete"] += 1
        else:
            stats["complete_1x2"] += 1
            competition = (
                event.get("ECN")
                or event.get("CN")
                or event.get("competition")
                or "Unknown"
            )
            kickoff = event.get("D") or event.get("kickoff")
            if kickoff is None:
                kickoff = datetime.now(timezone.utc)
            parsed.append(
                {
                    "event_id": event_id,
                    "competition": competition,
                    "sport": event.get("ESN") or event.get("SN") or sport,
                    "home": home,
                    "away": away,
                    "kickoff": kickoff,
                    "home_odds": prices[0],
                    "draw_odds": prices[1],
                    "away_odds": prices[2],
                }
            )

        ou_lines = _extract_over_under(event)
        if ou_lines:
            stats["over_under_markets"] = stats.get("over_under_markets", 0) + 1
        competition = (
            event.get("ECN")
            or event.get("CN")
            or event.get("competition")
            or "Unknown"
        )
        kickoff = event.get("D") or event.get("kickoff")
        if kickoff is None:
            kickoff = datetime.now(timezone.utc)
        for line, (over_odds, under_odds) in ou_lines.items():
            if line != TARGET_OU_LINE:
                continue
            stats["complete_ou_2_5"] = stats.get("complete_ou_2_5", 0) + 1
            parsed.append(
                {
                    "event_id": event_id,
                    "competition": competition,
                    "sport": event.get("ESN") or event.get("SN") or sport,
                    "home": home,
                    "away": away,
                    "kickoff": kickoff,
                    "market": "over_under",
                    "line": line,
                    "home_odds": over_odds,
                    "draw_odds": 0.0,
                    "away_odds": under_odds,
                    "over_odds": over_odds,
                    "under_odds": under_odds,
                }
            )

    stats["matchodds_produced"] = len(parsed)
    return parsed, stats


def summarize_structure(data, max_depth=4, depth=0):
    """Compact type/key tree for forensics. No odds dumps."""
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "bool"
    if isinstance(data, (int, float)):
        return type(data).__name__
    if isinstance(data, str):
        return f"str(len={len(data)})"
    if isinstance(data, list):
        if not data:
            return {"type": "list", "length": 0}
        return {
            "type": "list",
            "length": len(data),
            "first": summarize_structure(data[0], max_depth, depth + 1)
            if depth < max_depth
            else f"{type(data[0]).__name__}",
        }
    if isinstance(data, dict):
        if depth >= max_depth:
            return {"type": "dict", "keys": list(data.keys())[:20]}
        return {
            "type": "dict",
            "keys": list(data.keys()),
            "fields": {
                key: summarize_structure(value, max_depth, depth + 1)
                for key, value in list(data.items())[:24]
            },
        }
    return type(data).__name__
