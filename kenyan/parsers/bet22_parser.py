"""
22Bet parser.

RECONNAISSANCE FINDINGS (live-verified 2026-08-30; see
kenyan/fixtures/bet22_*.json for the captured, trimmed real payloads
used by this module's tests):

- `GetSportsShortZip` (`.../LiveFeed/GetSportsShortZip?...` and the
  `LineFeed` equivalent) is CONFIRMED to be navigation/index data only
  -- e.g. `{"I": 1, "N": "Football", "C": 1768, "CC": 325, ...}` -- a
  sport/league tree with counts, no event ids, no teams, no odds. This
  module never treats it as match data, per the task's explicit
  warning; it is unused by this parser/worker entirely (the live and
  prematch 1x2 endpoints below need no input from it).

- `LiveFeed/Get1x2_VZip` and `LineFeed/Get1x2_VZip` are the actual
  match+odds endpoints, for live and prematch respectively. Both
  return `{"Id", "Success", ..., "Value": [...]}` where `Value` is a
  list of event objects using the exact same "flat" `E`-list numeric
  convention as 1xBet (`T`=outcome type, `C`=price, `G`=group,
  `B`=blocked) -- see kenyan/parsers/_common_1x2.py, confirmed the
  same way: a live Chelsea 4-2 Brighton event shows `T:1` (home/
  Chelsea) priced at 1.025 and `T:3` (away/Brighton) at 51, i.e.
  type 1/2/3 = home/draw/away, group 1 = the main 1X2 market.

- Team names/participants: `O1` (always home) / `O2` (away). Sport
  filter: `SI == 1` (also carries `SN == "Football"`).
  Timestamp: `S`, unix seconds (UTC).

- The prematch feed also contains OUTRIGHT/other non-match "events"
  using placeholder participants `"Home"`/`"Away"` (observed team ids
  142205/142207, and/or a `homeAwayFlag` field) -- these are rejected
  here since they are not real fixtures.
"""
from datetime import datetime, timezone

from kenyan.config import BET22
from kenyan.date_utils import unix_seconds_to_datetime
from kenyan.log import log_parse
from kenyan.markets import (
    FAMILY_TOTAL,
    FAMILY_WINNER,
    MARKET_MATCH_WINNER,
    MARKET_TOTAL,
    PERIOD_FULL_MATCH,
    finalize_match,
    market_label,
)
from kenyan.models import KenyanMatchOdds
from kenyan.parsers._common_1x2 import extract_1x2_clusters_from_flat_events
from kenyan.parsers._common_markets import (
    BASKETBALL_MONEYLINE_GROUP_ID,
    extract_totals_from_flat_events,
    extract_two_way_winner_from_flat_events,
)

FOOTBALL_SPORT_ID = 1
SPORT_BY_ID = {
    1: "Football",
    3: "Basketball",
    4: "Tennis",
    6: "Volleyball",
}

_PLACEHOLDER_TEAM_IDS = {142205, 142207}
_PLACEHOLDER_TEAM_NAMES = {"home", "away"}


def _is_placeholder_fixture(event: dict) -> bool:
    if event.get("homeAwayFlag"):
        return True

    home_id = event.get("O1I")
    away_id = event.get("O2I")
    if home_id in _PLACEHOLDER_TEAM_IDS or away_id in _PLACEHOLDER_TEAM_IDS:
        return True

    home_name = (event.get("O1") or "").strip().lower()
    away_name = (event.get("O2") or "").strip().lower()
    if home_name in _PLACEHOLDER_TEAM_NAMES and away_name in _PLACEHOLDER_TEAM_NAMES:
        return True

    return False


def parse_events(payload, *, status: str, reference_now=None) -> list:
    """
    Parses either the live or prematch 22Bet `Get1x2_VZip` payload
    (both share the same "flat" shape) into normalized
    KenyanMatchOdds. `status` must be "LIVE" or "PREMATCH".
    """

    now = datetime.now(timezone.utc)
    reference = reference_now or now
    results = []

    events = payload.get("Value") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        events = []

    for event in events:
        if not isinstance(event, dict):
            continue

        if event.get("SI") != FOOTBALL_SPORT_ID:
            continue

        if _is_placeholder_fixture(event):
            continue

        home_team = event.get("O1")
        away_team = event.get("O2")
        if not home_team or not away_team:
            continue

        start_ts = event.get("S")
        if start_ts is None:
            continue

        start_time = unix_seconds_to_datetime(start_ts)

        clusters = extract_1x2_clusters_from_flat_events(event.get("E"))
        if not clusters:
            continue

        chosen = clusters[0]
        prices = chosen["prices"]
        competition = event.get("L") or ""
        event_id = event.get("I")
        home_team_id = "" if event.get("O1I") is None else str(event.get("O1I"))
        away_team_id = "" if event.get("O2I") is None else str(event.get("O2I"))

        match = KenyanMatchOdds(
            bookmaker=BET22,
            competition=competition,
            sport="Football",
            market="1X2",
            home_team=home_team,
            away_team=away_team,
            home_odds=prices[1],
            draw_odds=prices[2],
            away_odds=prices[3],
            start_time=start_time,
            collected_at=now,
            event_id=str(event_id),
            cluster_id=chosen["cluster_id"],
            market_id=chosen["market_id"],
            parent_event_id=str(event_id),
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            status=status,
            source=f"bet22_{status.lower()}",
        )
        log_parse(
            BET22,
            event=f"{home_team} vs {away_team}",
            status="parsed",
            market="MATCH_WINNER",
            selection="HOME",
            event_id=match.event_id,
            cluster_id=match.cluster_id,
            market_id=match.market_id,
        )
        results.append(match)

    return results


def parse_extra_markets(payload, *, status: str, reference_now=None) -> list:
    now = datetime.now(timezone.utc)
    reference = reference_now or now
    results = []

    events = payload.get("Value") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        events = []

    for event in events:
        if not isinstance(event, dict):
            continue
        sport_id = event.get("SI")
        if sport_id not in SPORT_BY_ID:
            continue
        if _is_placeholder_fixture(event):
            continue
        home_team = event.get("O1")
        away_team = event.get("O2")
        if not home_team or not away_team:
            continue
        start_ts = event.get("S")
        if start_ts is None:
            continue
        start_time = unix_seconds_to_datetime(start_ts)

        sport = SPORT_BY_ID[sport_id]
        competition = event.get("L") or ""
        event_id = event.get("I")
        home_team_id = "" if event.get("O1I") is None else str(event.get("O1I"))
        away_team_id = "" if event.get("O2I") is None else str(event.get("O2I"))
        base = dict(
            bookmaker=BET22,
            competition=competition,
            sport=sport,
            home_team=home_team,
            away_team=away_team,
            start_time=start_time,
            collected_at=now,
            event_id=str(event_id),
            parent_event_id=str(event_id),
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            status=status,
            source=f"bet22_{status.lower()}",
        )

        if sport != "Football":
            winner = extract_two_way_winner_from_flat_events(event.get("E"))
            if not winner and sport_id == 3:
                winner = extract_two_way_winner_from_flat_events(
                    event.get("E"),
                    group_id=BASKETBALL_MONEYLINE_GROUP_ID,
                    home_type=401,
                    away_type=402,
                )
            if winner:
                match = KenyanMatchOdds(
                    **base,
                    market="MATCH_WINNER",
                    home_odds=winner["home"],
                    draw_odds=None,
                    away_odds=winner["away"],
                    cluster_id=winner["cluster_id"],
                    market_id=winner["market_id"],
                    market_type=MARKET_MATCH_WINNER,
                    period=PERIOD_FULL_MATCH,
                    outcome_family=FAMILY_WINNER,
                )
                log_parse(
                    BET22,
                    event=f"{home_team} vs {away_team}",
                    status="parsed",
                    market="MATCH_WINNER",
                    event_id=match.event_id,
                )
                results.append(finalize_match(match))

        for total in extract_totals_from_flat_events(event.get("E")):
            match = KenyanMatchOdds(
                **base,
                market="over_under",
                home_odds=total["over"],
                draw_odds=None,
                away_odds=total["under"],
                cluster_id=total["cluster_id"],
                market_id=total["market_id"],
                line=total["line"],
                market_type=MARKET_TOTAL,
                period=PERIOD_FULL_MATCH,
                outcome_family=FAMILY_TOTAL,
            )
            match.market_label = market_label(match)
            results.append(finalize_match(match))

    return results


def parse_all_markets(payload, *, status: str, reference_now=None) -> list:
    return parse_events(payload, status=status, reference_now=reference_now) + parse_extra_markets(
        payload, status=status, reference_now=reference_now
    )
