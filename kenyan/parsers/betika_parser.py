"""
Betika parser.

RECONNAISSANCE FINDINGS (live-verified 2026-08-30; see
kenyan/fixtures/betika_live.json / betika_prematch.json for the
captured, trimmed real payloads used by this module's tests):

- LIVE: `https://live.betika.com/v1/uo/matches?page=1&limit=...&
  sub_type_id=1,186,340&sport=null&sort=1` returns
  `{"data": [{...match...}], "meta": {...}}`.
- PREMATCH: `https://api.betika.com/v1/uo/matches?page=1&limit=...&
  sub_type_id=1,186,340&sport=1` returns the SAME shape
  (`{"data": [...]}`) -- just a different host, and without the
  live-only fields (`current_score`, `match_time`, etc). This module
  therefore shares one parsing function for both, driven only by the
  caller-supplied `status` ("LIVE"/"PREMATCH"), matching how the real
  API itself does not distinguish the two by any payload field other
  than which host answered the request.
- Each match carries `sport_name` ("Soccer" for football) and an
  `odds` list of markets, e.g.
  `{"sub_type_id": 1, "name": "1X2", "odds": [{"outcome_id": "1",
  "odd_value": "1.38", ...}, {"outcome_id": "2", ...(draw)},
  {"outcome_id": "3", ...}]}`. `outcome_id` "1"/"2"/"3" reliably means
  home/draw/away (cross-checked against the top-level convenience
  fields `home_odd`/`neutral_odd`/`away_odd`, which always matched).
- `start_time` is a `"YYYY-MM-DD HH:MM:SS"` string in Kenya local time
  (verified: the API's own `current_timestamp`/`NOW` fields, compared
  against the HTTP response's `Date` header, run ~3 hours ahead of
  UTC -- i.e. EAT).
"""
from datetime import datetime, timezone

from kenyan.config import BETIKA
from kenyan.date_utils import KENYA_TZ, is_today_in_kenya
from kenyan.markets import (
    FAMILY_TOTAL,
    FAMILY_WINNER,
    MARKET_MATCH_WINNER,
    MARKET_TOTAL,
    PERIOD_FULL_MATCH,
    finalize_match,
    market_label,
    sport_display,
    sport_key,
)
from kenyan.models import KenyanMatchOdds
from kenyan.odds import parse_decimal_odds

FOOTBALL_SPORT_NAME = "soccer"
ONE_X_TWO_SUB_TYPE_ID = 1
WINNER_SUB_TYPE_IDS = {"186", "340", "113"}
SUPPORTED_SPORT_KEYS = {"football", "tennis", "basketball", "volleyball"}
SPORT_ID_TO_NAME = {
    "14": "Football",
    "28": "Tennis",
    "30": "Basketball",
    "35": "Volleyball",
}


def _parse_kenya_local_datetime(value):
    if not value:
        return None
    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=KENYA_TZ).astimezone(timezone.utc)


def _extract_1x2_odds(match: dict):
    home_odds = draw_odds = away_odds = None

    markets = match.get("odds")
    if not isinstance(markets, list):
        return home_odds, draw_odds, away_odds

    for market in markets:
        if not isinstance(market, dict):
            continue

        # Observed live: `sub_type_id` is an int on the LIVE feed but a
        # string on the PREMATCH feed for the identical market -- compare
        # as strings so both are recognized.
        if str(market.get("sub_type_id")) != str(ONE_X_TWO_SUB_TYPE_ID):
            continue

        outcomes = market.get("odds")
        if not isinstance(outcomes, list):
            continue

        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            outcome_id = outcome.get("outcome_id")
            price = parse_decimal_odds(outcome.get("odd_value"))
            if price is None:
                continue

            if outcome_id == "1":
                home_odds = price
            elif outcome_id == "2":
                draw_odds = price
            elif outcome_id == "3":
                away_odds = price

        break  # only one 1X2 market expected per match

    return home_odds, draw_odds, away_odds


def parse_matches(
    payload: dict,
    *,
    status: str,
    reference_now=None,
) -> list:
    """
    Shared parser for both the live and prematch Betika feeds (see
    module docstring for why they share one function). `status` must
    be "LIVE" or "PREMATCH" -- it comes from the worker, not the
    payload, since the payload shape does not otherwise distinguish
    the two.

    For PREMATCH, only fixtures scheduled for today (Kenya local date)
    are kept. For LIVE, every returned match is, by construction of the
    live endpoint itself, already in progress.
    """

    now = datetime.now(timezone.utc)
    results = []

    raw_matches = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_matches, list):
        raw_matches = []

    for match in raw_matches:
        if not isinstance(match, dict):
            continue

        sport_name = (match.get("sport_name") or "").strip().lower()
        if sport_name != FOOTBALL_SPORT_NAME:
            continue

        home_team = match.get("home_team")
        away_team = match.get("away_team")
        if not home_team or not away_team:
            continue

        start_time = _parse_kenya_local_datetime(match.get("start_time"))
        if start_time is None:
            continue

        if status == "PREMATCH" and not is_today_in_kenya(
            start_time, reference=reference_now or now
        ):
            continue

        home_odds, draw_odds, away_odds = _extract_1x2_odds(match)
        if home_odds is None or draw_odds is None or away_odds is None:
            continue

        event_id = match.get("match_id") or match.get("game_id") or ""
        competition = match.get("competition_name") or match.get("competition") or ""

        results.append(
            KenyanMatchOdds(
                bookmaker=BETIKA,
                competition=competition,
                sport="Football",
                market="1X2",
                home_team=home_team,
                away_team=away_team,
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                start_time=start_time,
                collected_at=now,
                event_id=str(event_id),
                status=status,
                source=f"betika_{status.lower()}",
            )
        )

    return results


def _iter_matches(payload):
    raw_matches = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_matches, list):
        return []
    return [row for row in raw_matches if isinstance(row, dict)]


def _sport_name_for_match(match: dict) -> str:
    sport_id = str(match.get("sport_id") or "")
    if sport_id in SPORT_ID_TO_NAME:
        return SPORT_ID_TO_NAME[sport_id]
    return sport_display(match.get("sport_name") or "")


def _extract_two_way_winner(match: dict):
    markets = match.get("odds")
    if not isinstance(markets, list):
        return None
    for market in markets:
        if not isinstance(market, dict):
            continue
        sub_type = str(market.get("sub_type_id") or "")
        name = (market.get("name") or "").strip().upper()
        if sub_type not in WINNER_SUB_TYPE_IDS and name not in {"WINNER", "MATCH WINNER"}:
            continue
        outcomes = market.get("odds")
        if not isinstance(outcomes, list):
            continue
        home = away = None
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            price = parse_decimal_odds(outcome.get("odd_value"))
            if price is None:
                continue
            display = str(outcome.get("display") or "").strip()
            outcome_id = str(outcome.get("outcome_id") or "")
            if display in {"1", "HOME"} or outcome_id in {"4", "1"}:
                if home is None:
                    home = price
            elif display in {"2", "AWAY"} or outcome_id in {"5", "3"}:
                if away is None:
                    away = price
        if home is not None and away is not None:
            return home, away, sub_type or "winner"
    return None


def _extract_totals(match: dict):
    markets = match.get("odds")
    if not isinstance(markets, list):
        return []
    totals = []
    for market in markets:
        if not isinstance(market, dict):
            continue
        name = (market.get("name") or "").strip().lower()
        if "over" not in name and "under" not in name and "total" not in name:
            continue
        outcomes = market.get("odds")
        if not isinstance(outcomes, list):
            continue
        over = under = line = None
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            price = parse_decimal_odds(outcome.get("odd_value"))
            if price is None:
                continue
            special = outcome.get("special_bet_value") or outcome.get("parsed_special_bet_value")
            if line is None:
                candidate = special
                if isinstance(candidate, dict):
                    candidate = next(iter(candidate.values()), None)
                try:
                    if candidate not in (None, ""):
                        line = round(float(candidate), 2)
                except (TypeError, ValueError):
                    line = None
            key = (outcome.get("odd_key") or outcome.get("display") or "").strip().lower()
            if "over" in key or str(outcome.get("display") or "").lower() in {"over", "o"}:
                over = price
            elif "under" in key or str(outcome.get("display") or "").lower() in {"under", "u"}:
                under = price
        if over is not None and under is not None and line is not None:
            totals.append((line, over, under, str(market.get("sub_type_id") or "total")))
    return totals


def parse_extra_matches(payload: dict, *, status: str, reference_now=None) -> list:
    """Tennis/basketball/volleyball winners plus any totals present on the payload."""
    now = datetime.now(timezone.utc)
    results = []
    for match in _iter_matches(payload):
        sport = _sport_name_for_match(match)
        if sport_key(sport) not in SUPPORTED_SPORT_KEYS:
            continue
        if sport_key(sport) == "football":
            for line, over, under, market_id in _extract_totals(match):
                built = _build_betika_match(
                    match,
                    sport="Football",
                    status=status,
                    now=now,
                    reference_now=reference_now,
                    market="over_under",
                    home_odds=over,
                    draw_odds=None,
                    away_odds=under,
                    line=line,
                    market_type=MARKET_TOTAL,
                    outcome_family=FAMILY_TOTAL,
                    market_id=market_id,
                )
                if built is not None:
                    results.append(built)
            continue

        home_team = match.get("home_team")
        away_team = match.get("away_team")
        if not home_team or not away_team:
            continue

        if sport_key(sport) == "basketball":
            home_odds, draw_odds, away_odds = _extract_1x2_odds(match)
            if home_odds is not None and draw_odds is not None and away_odds is not None:
                built = _build_betika_match(
                    match,
                    sport=sport,
                    status=status,
                    now=now,
                    reference_now=reference_now,
                    market="1X2",
                    home_odds=home_odds,
                    draw_odds=draw_odds,
                    away_odds=away_odds,
                    market_type=MARKET_MATCH_WINNER,
                    outcome_family=FAMILY_WINNER,
                    market_id="1",
                )
                if built is not None:
                    results.append(built)
            else:
                two_way = _extract_two_way_winner(match)
                if two_way:
                    home_odds, away_odds, market_id = two_way
                    built = _build_betika_match(
                        match,
                        sport=sport,
                        status=status,
                        now=now,
                        reference_now=reference_now,
                        market="MATCH_WINNER",
                        home_odds=home_odds,
                        draw_odds=None,
                        away_odds=away_odds,
                        market_type=MARKET_MATCH_WINNER,
                        outcome_family=FAMILY_WINNER,
                        market_id=market_id,
                    )
                    if built is not None:
                        results.append(built)
        else:
            two_way = _extract_two_way_winner(match)
            if two_way:
                home_odds, away_odds, market_id = two_way
                built = _build_betika_match(
                    match,
                    sport=sport,
                    status=status,
                    now=now,
                    reference_now=reference_now,
                    market="MATCH_WINNER",
                    home_odds=home_odds,
                    draw_odds=None,
                    away_odds=away_odds,
                    market_type=MARKET_MATCH_WINNER,
                    outcome_family=FAMILY_WINNER,
                    market_id=market_id,
                )
                if built is not None:
                    results.append(built)

        for line, over, under, market_id in _extract_totals(match):
            built = _build_betika_match(
                match,
                sport=sport,
                status=status,
                now=now,
                reference_now=reference_now,
                market="over_under",
                home_odds=over,
                draw_odds=None,
                away_odds=under,
                line=line,
                market_type=MARKET_TOTAL,
                outcome_family=FAMILY_TOTAL,
                market_id=market_id,
            )
            if built is not None:
                results.append(built)
    return results


def _build_betika_match(
    match,
    *,
    sport,
    status,
    now,
    reference_now,
    market,
    home_odds,
    draw_odds,
    away_odds,
    market_type,
    outcome_family,
    market_id,
    line=None,
):
    start_time = _parse_kenya_local_datetime(match.get("start_time"))
    if start_time is None:
        return None
    if status == "PREMATCH" and not is_today_in_kenya(
        start_time, reference=reference_now or now
    ):
        return None
    event_id = match.get("match_id") or match.get("game_id") or ""
    competition = match.get("competition_name") or match.get("competition") or ""
    built = KenyanMatchOdds(
        bookmaker=BETIKA,
        competition=competition,
        sport=sport,
        market=market,
        home_team=match.get("home_team"),
        away_team=match.get("away_team"),
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=start_time,
        collected_at=now,
        event_id=str(event_id),
        market_id=str(market_id),
        line=line,
        status=status,
        source=f"betika_{status.lower()}",
        market_type=market_type,
        period=PERIOD_FULL_MATCH,
        outcome_family=outcome_family,
    )
    built.market_label = market_label(built)
    return finalize_match(built)


def parse_all_matches(payload: dict, *, status: str, reference_now=None) -> list:
    return parse_matches(payload, status=status, reference_now=reference_now) + parse_extra_matches(
        payload, status=status, reference_now=reference_now
    )
