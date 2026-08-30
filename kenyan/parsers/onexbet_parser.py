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
from kenyan.parsers._common_1x2 import (
    extract_1x2_from_event_groups,
    extract_1x2_from_flat_events,
    is_complete_1x2,
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


def _parse_one_event(event, *, status: str, now, today_reference):
    if not isinstance(event, dict):
        return None

    if "eventGroups" in event:
        sport = event.get("sport") or {}
        if sport.get("id") != FOOTBALL_SPORT_ID:
            return None

        home_team = (event.get("opponent1") or {}).get("fullName")
        away_team = (event.get("opponent2") or {}).get("fullName")
        competition = (event.get("liga") or {}).get("name") or ""
        event_id = event.get("id")
        start_ts = event.get("startTs")

        prices = extract_1x2_from_event_groups(event.get("eventGroups"))
    else:
        if event.get("SI") != FOOTBALL_SPORT_ID:
            return None

        home_team = event.get("O1")
        away_team = event.get("O2")
        competition = event.get("L") or ""
        event_id = event.get("I")
        start_ts = event.get("S")

        prices = extract_1x2_from_flat_events(event.get("E"))

    if not home_team or not away_team:
        return None

    if _is_placeholder_fixture(home_team, away_team):
        return None

    if not is_complete_1x2(prices):
        return None

    if start_ts is None:
        return None

    start_time = unix_seconds_to_datetime(start_ts)

    if status == "PREMATCH" and not is_today_in_kenya(
        start_time, reference=today_reference
    ):
        return None

    return KenyanMatchOdds(
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
        status=status,
        source=f"onexbet_{status.lower()}",
    )


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
