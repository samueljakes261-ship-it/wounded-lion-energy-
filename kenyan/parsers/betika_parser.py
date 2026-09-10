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
from kenyan.models import KenyanMatchOdds

FOOTBALL_SPORT_NAME = "soccer"
ONE_X_TWO_SUB_TYPE_ID = 1


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
            try:
                price = float(outcome.get("odd_value"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
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
