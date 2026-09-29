"""
1xBet parser.

RECONNAISSANCE FINDINGS (live-verified 2026-08-30, INCLUDING a
same-day re-verification pass after an earlier draft of this module
had mistakenly assumed prematch used a different shape -- see
kenyan/fixtures/onexbet_live.json / onexbet_prematch.json for the
captured, trimmed real payloads used by this module's tests):

- BOTH LIVE (`.../main-live-feed/v3/games1x2?...`) AND PREMATCH
  (`.../main-line-feed/v3/games1x2?...`) return a bare JSON LIST of
  event objects using the SAME "grouped" `eventGroups` shape (see
  kenyan/parsers/_common_1x2.py) -- confirmed directly: both endpoints'
  real responses carry `opponent1`/`opponent2`/`eventGroups`/`startTs`,
  with no `{"Id","Success","Value":[...]}` envelope at all. (An
  earlier assumption that prematch used a "flat" `E`-list envelope was
  based on a mislabeled sample and has been corrected; that flat shape
  turned out to belong to 22Bet instead -- see bet22_parser.py.) This
  parser therefore branches on the PAYLOAD'S OWN SHAPE
  (`"eventGroups" in event`) rather than on which endpoint was called,
  so it stays correct even if either endpoint's shape ever changes
  independently of the other.
- The task's reconnaissance notes suggested `type 1 = HOME, type 2 =
  DRAW, type 3 = AWAY` within `groupId`/`G` == 1 -- this was VERIFIED
  against real in-play data rather than assumed: e.g. a live event with
  Chelsea (O1/opponent1) leading Brighton (O2/opponent2) 4-2 showed
  type 1 (Chelsea/home) at cf=1.025 (correctly the short-priced
  favourite already winning) and type 3 (Brighton/away) at cf=51 (a
  huge outsider, consistent with being 2 goals down) -- confirming
  type 1/2/3 = home/draw/away, not some other ordering.
- Team names/participants: `opponent1.fullName`/`opponent2.fullName`
  (grouped shape) or `O1`/`O2` (flat shape, kept as a defensive
  fallback even though not observed live for 1xBet) -- opponent1/O1 is
  always the home side.
- Sport/football filter: `sport.id == 1` (grouped shape) or `SI == 1`
  (flat shape); both also carry a human-readable name ("Football").
- Timestamps: `startTs` (grouped) / `S` (flat) are unix seconds (UTC).
- Blocked odds: an outcome dict can carry `"blocked": true` (grouped
  shape) or `"B": true` (flat shape) -- both are treated as
  unavailable and excluded by `kenyan/parsers/_common_1x2.py`.
- PREMATCH also contains OUTRIGHT/non-match "events" with placeholder
  participants (`opponent1.fullName == "Home"`, `opponent2.fullName ==
  "Away"`, ids 142205/142207) -- the same artifact confirmed on 22Bet's
  platform (they share the same underlying odds provider). These are
  rejected here.
"""
from datetime import datetime, timezone

from kenyan.config import ONEXBET
from kenyan.date_utils import is_today_in_kenya, unix_seconds_to_datetime
from kenyan.models import KenyanMatchOdds
from kenyan.log import log_parse
from kenyan.parsers._common_1x2 import (
    extract_1x2_clusters_from_event_groups,
    extract_1x2_clusters_from_flat_events,
)

FOOTBALL_SPORT_ID = 1

_PLACEHOLDER_TEAM_NAMES = {"home", "away"}


def _is_placeholder_fixture(home_team, away_team) -> bool:
    return (
        (home_team or "").strip().lower() in _PLACEHOLDER_TEAM_NAMES
        and (away_team or "").strip().lower() in _PLACEHOLDER_TEAM_NAMES
    )


def iter_events(payload):
    """
    Accepts either the bare-list live shape or the {"Value": [...]}
    prematch envelope, and yields raw event dicts either way. Public
    (no leading underscore) since kenyan/workers/onexbet.py also uses
    this to build its diagnostics without duplicating the shape check.
    """

    if isinstance(payload, dict):
        events = payload.get("Value")
    else:
        events = payload

    return events if isinstance(events, list) else []


def _opponent_id(opponent) -> str:
    if not isinstance(opponent, dict):
        return ""
    opps = opponent.get("opps")
    if isinstance(opps, list) and opps and isinstance(opps[0], dict):
        value = opps[0].get("id")
        return "" if value is None else str(value)
    value = opponent.get("id")
    return "" if value is None else str(value)


def _is_satellite_event(event: dict) -> bool:
    """
    Period/special games reuse the same opponent names as the main
    fixture. Observed live payloads tag the main game with
    id == mainGameId and an empty periodName. Anything else is a
    different market cluster and must not enter MATCH_WINNER.
    """
    period_name = (event.get("periodName") or "").strip()
    if period_name:
        return True
    event_id = event.get("id")
    main_game_id = event.get("mainGameId")
    if main_game_id not in (None, "") and event_id not in (None, "") and main_game_id != event_id:
        return True
    return False


def _parse_one_event(event, *, status: str, now, today_reference):
    if not isinstance(event, dict):
        return None

    home_team_id = ""
    away_team_id = ""
    league_id = ""
    parent_event_id = ""

    if "eventGroups" in event:
        sport = event.get("sport") or {}
        if sport.get("id") != FOOTBALL_SPORT_ID:
            return None

        if _is_satellite_event(event):
            log_parse(
                ONEXBET,
                event=f"{(event.get('opponent1') or {}).get('fullName')} vs {(event.get('opponent2') or {}).get('fullName')}",
                status="rejected",
                market="1X2",
                event_id=str(event.get("id") or ""),
                reason="CLUSTER_MISMATCH",
            )
            return None

        home_opp = event.get("opponent1") or {}
        away_opp = event.get("opponent2") or {}
        home_team = home_opp.get("fullName")
        away_team = away_opp.get("fullName")
        liga = event.get("liga") or {}
        competition = liga.get("name") or ""
        league_id = "" if liga.get("id") is None else str(liga.get("id"))
        event_id = event.get("id")
        parent_event_id = "" if event.get("mainGameId") is None else str(event.get("mainGameId"))
        home_team_id = _opponent_id(home_opp)
        away_team_id = _opponent_id(away_opp)
        start_ts = event.get("startTs")
        clusters = extract_1x2_clusters_from_event_groups(event.get("eventGroups"))
    else:
        if event.get("SI") != FOOTBALL_SPORT_ID:
            return None

        home_team = event.get("O1")
        away_team = event.get("O2")
        competition = event.get("L") or ""
        event_id = event.get("I")
        home_team_id = "" if event.get("O1I") is None else str(event.get("O1I"))
        away_team_id = "" if event.get("O2I") is None else str(event.get("O2I"))
        start_ts = event.get("S")
        clusters = extract_1x2_clusters_from_flat_events(event.get("E"))

    if not home_team or not away_team:
        return None

    if _is_placeholder_fixture(home_team, away_team):
        return None

    if not clusters:
        return None

    chosen = clusters[0]
    prices = chosen["prices"]

    if start_ts is None:
        return None

    start_time = unix_seconds_to_datetime(start_ts)

    if status == "PREMATCH" and not is_today_in_kenya(
        start_time, reference=today_reference
    ):
        return None

    match = KenyanMatchOdds(
        bookmaker=ONEXBET,
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
        parent_event_id=parent_event_id or str(event_id),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        league_id=league_id,
        status=status,
        source=f"onexbet_{status.lower()}",
    )
    log_parse(
        ONEXBET,
        event=f"{home_team} vs {away_team}",
        status="parsed",
        market="MATCH_WINNER",
        selection="HOME",
        event_id=match.event_id,
        cluster_id=match.cluster_id,
        market_id=match.market_id,
    )
    return match


def parse_events(payload, *, status: str, reference_now=None) -> list:
    """
    Parses either the live (bare list, `eventGroups` shape) or
    prematch (`{"Value": [...]}`, flat `E` shape) 1xBet payload into
    normalized KenyanMatchOdds. `status` must be "LIVE" or "PREMATCH".
    """

    now = datetime.now(timezone.utc)
    reference = reference_now or now
    results = []

    for event in iter_events(payload):
        parsed = _parse_one_event(
            event, status=status, now=now, today_reference=reference
        )
        if parsed is not None:
            results.append(parsed)

    return results
