from typing import List

from debug import odds_trace

# Confirmed from decrypted BetKanyon payloads (experiments/decrypt/first_event.json):
# StakeTypes.Id 3 / -3, N="Toplam", SN="Üst"/"Alt", line in stake["A"], odds in stake["F"].
_OU_MARKET_IDS = {3, -3, "3", "-3"}
_OU_OVER_SN = {"üst", "ust"}
_OU_UNDER_SN = {"alt"}
_TARGET_OU_LINE = 2.5
_MIN_ODDS = 1.01
_MAX_ODDS = 100.0
_HOME_TOKENS = {"1", "w1", "win1", "home", "ev sahibi", "evsahibi", "kazanan1"}
_DRAW_TOKENS = {"x", "draw", "beraberlik", "berabere"}
_AWAY_TOKENS = {"2", "w2", "win2", "away", "deplasman", "kazanan2"}


def _norm_token(value):
    return str(value or "").strip().lower().replace("ç", "c")


def _selection_side(stake):
    token = _norm_token(stake.get("SN") or stake.get("N"))
    if token in _HOME_TOKENS:
        return "home"
    if token in _DRAW_TOKENS:
        return "draw"
    if token in _AWAY_TOKENS:
        return "away"
    sc = stake.get("SC", stake.get("sc"))
    if sc in (1, "1", 1.0):
        return "home"
    if sc in (2, "2", 2.0):
        return "draw"
    if sc in (3, "3", 3.0):
        return "away"
    return None


def _plausible_price(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds != odds or odds in (float("inf"), float("-inf")):
        return None
    if _MIN_ODDS <= odds <= _MAX_ODDS:
        return odds
    return None


def _extract_over_under_lines(event) -> dict:
    """Return {line: {"over": odds, "under": odds}} for Toplam markets."""
    by_line = {}
    for market in event.get("StakeTypes", []):
        if market.get("Id") not in _OU_MARKET_IDS:
            continue
        for stake in market.get("Stakes", []):
            line_raw = stake.get("A")
            price = _plausible_price(stake.get("F"))
            if line_raw is None or price is None:
                continue
            try:
                line = round(float(line_raw), 2)
            except (TypeError, ValueError):
                continue
            selection = str(stake.get("SN") or stake.get("N") or "").strip().lower()
            bucket = by_line.setdefault(line, {"over": None, "under": None})
            if selection in _OU_OVER_SN:
                bucket["over"] = price
            elif selection in _OU_UNDER_SN:
                bucket["under"] = price
    return by_line


def parse_json(data) -> List[dict]:

    matches = []

    # Sport
    for country in data.get("CNT", []):

        # Competition
        for competition in country.get("CL", []):

            # Events
            for event in competition.get("E", []):

                home = event.get("EHT") or event.get("HT")
                away = event.get("EAT") or event.get("AT")

                kickoff = event.get("D")

                home_price = None
                draw_price = None
                away_price = None

                for market in event.get("StakeTypes", []):

                    # Match Odds market
                    if market.get("Id") != 1:
                        continue

                    for stake in market.get("Stakes", []):
                        price = stake.get("F")
                        side = _selection_side(stake)
                        if side == "home":
                            home_price = price
                        elif side == "draw":
                            draw_price = price
                        elif side == "away":
                            away_price = price

                if (
                    home_price is not None
                    and draw_price is not None
                    and away_price is not None
                ):

                    home_odds = float(home_price)
                    draw_odds = float(draw_price)
                    away_odds = float(away_price)

                    # RAW == the exact value BetKanyon's own JSON
                    # carried (a string or number, e.g. "F": "2.15");
                    # PARSED == that same value cast to float. Traced
                    # together so a discrepancy introduced by the
                    # float() cast itself (there should never be one)
                    # is visible, not assumed away.
                    odds_trace.record(
                        "PARSED",
                        "Betkanyon",
                        home,
                        away,
                        "Match Odds",
                        None,
                        home_odds,
                        draw_odds,
                        away_odds,
                        raw={
                            "home": home_price,
                            "draw": draw_price,
                            "away": away_price,
                        },
                    )

                    matches.append(
                        {
                            "event_id": event.get("Id"),
                            "competition": competition.get("EGN")
                            or competition.get("N"),
                            "sport": data.get("EGN")
                            or data.get("N"),
                            "home": home,
                            "away": away,
                            "kickoff": kickoff,
                            "home_odds": home_odds,
                            "draw_odds": draw_odds,
                            "away_odds": away_odds,
                        }
                    )

                competition_name = competition.get("EGN") or competition.get("N")
                sport_name = data.get("EGN") or data.get("N")
                for line, prices in _extract_over_under_lines(event).items():
                    if line != _TARGET_OU_LINE:
                        continue
                    over_odds = prices.get("over")
                    under_odds = prices.get("under")
                    if over_odds is None or under_odds is None:
                        continue
                    matches.append(
                        {
                            "event_id": event.get("Id"),
                            "competition": competition_name,
                            "sport": sport_name,
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

    return matches
