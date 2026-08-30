"""
SportPesa parser.

RECONNAISSANCE FINDINGS (live-verified against the real API on
2026-08-30; see kenyan/fixtures/sportpesa_*.json for the captured,
trimmed payloads used by this module's tests):

- `https://www.ke.sportpesa.com/...` (the "ke." subdomain given in the
  task) is behind an anti-bot JS proof-of-work challenge ("Challenge
  Validation" page) for every endpoint tried, even with a normal
  browser User-Agent -- it cannot be queried with a plain HTTP request,
  the same category of problem the existing OnWin/BetKanyon workers
  solve with a real browser session (ZenRows). See
  kenyan/workers/sportpesa.py for how this is handled without touching
  that existing browser/ZenRows infrastructure.

- `https://www.sportpesa.com/...` (no "ke." subdomain) serves the SAME
  API set over plain HTTPS with no anti-bot challenge. All fixtures and
  the worker's default base URL use this host.

- LIVE event discovery (`/api/live/sports/{sportId}/events`) returns
  `{"events": [{"id", "externalId", "sport": {"id","name"}, "tournament":
  {"name"}, "competitors": [home, away], "kickoffTimeUTC", "status", ...}]}`.
  `id` is SportPesa's own event id -- this is what the markets endpoint
  expects, NOT `externalId` (a Betradar-style cross-bookmaker id that
  happens to also appear on other bookmakers' payloads, but is not
  accepted by SportPesa's own markets endpoint).

- LIVE markets (`/api/live/event/markets?eventId=<comma-separated ids>&
  type=194%230%230&sportId=1`) returns
  `{"markets": [{"eventId", "markets": [{"id": 194, "name": "1x2",
  "selections": [{"name", "odds", "status"}, ...]}, ...]}, ...]}`.
  Market id **194** ("1x2") is the live 1X2 market -- confirmed live
  (the sample URL in the task spec references "194#0#0" as the first
  market code). Selections are identified by NAME against the
  discovery event's `competitors[0]`/`competitors[1]` (home/away, in
  that order) -- exactly like the existing Orbit adapter's own
  name-based approach (see parsers/orbit/adapter.py) -- with whichever
  selection isn't home/away treated as the draw.

- PREMATCH: `/api/todays/{sportId}/games?type=prematch&section=today&...`
  returns TODAY's football fixtures **with 1X2 odds already embedded**
  (market id 10, name "3 Way", `selections[*].shortName` in {"1","X","2"}),
  in ONE call -- no separate `/api/games/markets` round trip is needed.
  This was verified by direct comparison against
  `/api/games/markets?games=...&markets=...`: the `todays/{sport}/games`
  endpoint is date-scoped (`section=today`) by the API itself, paginated
  via `pag_min`/`pag_count`, and already carries full market data, so it
  is the more reliable source for "today's prematch football events and
  their odds" -- `games/markets` would require first harvesting today's
  game ids from somewhere else anyway. This module therefore uses
  `todays/{sport}/games` for prematch and does not use `games/markets`.
"""
from datetime import datetime, timezone
from typing import Optional

from kenyan.config import SPORTPESA
from kenyan.date_utils import is_today_in_kenya, unix_seconds_to_datetime
from kenyan.models import KenyanMatchOdds

LIVE_1X2_MARKET_ID = 194
PREMATCH_1X2_MARKET_ID = 10

SPORTPESA_BASE_URL = "https://www.sportpesa.com"


def build_live_discovery_url(*, limit: int = 50, offset: int = 0) -> str:
    return (
        f"{SPORTPESA_BASE_URL}/api/live/sports/1/events"
        f"?limit={limit}&offset={offset}"
    )


def build_live_markets_url(event_ids: list) -> str:
    """
    Constructs the live markets request DYNAMICALLY from whichever
    event ids were just discovered -- never from a hardcoded list.
    Only requests the 1x2 market (id 194) since that is all this
    module needs.
    """

    ids_param = ",".join(str(event_id) for event_id in event_ids)
    return (
        f"{SPORTPESA_BASE_URL}/api/live/event/markets"
        f"?eventId={ids_param}&type=194%230%230&sportId=1"
    )


def build_todays_games_url(*, page_min: int = 1, page_count: int = 100) -> str:
    return (
        f"{SPORTPESA_BASE_URL}/api/todays/1/games"
        f"?type=prematch&section=today&markets_layout=multiple"
        f"&o=startTime&pag_count={page_count}&pag_min={page_min}"
    )


def extract_live_football_events(discovery_payload: dict) -> list:
    """
    Step 1 of the live flow: extract the currently available football
    event ids (+ metadata needed later for name-matching selections)
    from the discovery payload. Non-football events are dropped here.
    """

    events = []

    raw_events = discovery_payload.get("events") if isinstance(discovery_payload, dict) else None
    if not isinstance(raw_events, list):
        raw_events = []

    for event in raw_events:
        if not isinstance(event, dict):
            continue

        sport = event.get("sport") or {}
        if not isinstance(sport, dict) or sport.get("id") != 1:
            continue

        competitors = event.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            continue
        if not all(isinstance(c, dict) for c in competitors):
            continue

        events.append(
            {
                "event_id": event.get("id"),
                "home_team": competitors[0].get("name"),
                "away_team": competitors[1].get("name"),
                "competition": (event.get("tournament") or {}).get("name") or "",
                "kickoff_utc": event.get("kickoffTimeUTC"),
            }
        )

    return events


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _selection_odds(selections: list, *, home_team: str, away_team: str):
    """
    Identifies home/draw/away by NAME (never by array position -- the
    live sample shows SportPesa does not guarantee ordering), matching
    the existing Orbit adapter's approach for the same underlying
    reason. A selection whose status isn't "Open" is treated as
    unavailable (rejected), per "reject blocked/unavailable odds".
    """

    home_price = draw_price = away_price = None

    if not isinstance(selections, list):
        return home_price, draw_price, away_price

    for selection in selections:
        if not isinstance(selection, dict):
            continue

        name = (selection.get("name") or "").strip()
        status = selection.get("status")

        if status != "Open":
            continue

        try:
            price = float(selection.get("odds"))
        except (TypeError, ValueError):
            continue

        if price <= 0:
            continue

        if name.lower() == (home_team or "").strip().lower():
            home_price = price
        elif name.lower() == (away_team or "").strip().lower():
            away_price = price
        elif name.lower() == "draw":
            draw_price = price

    return home_price, draw_price, away_price


def parse_live_markets(
    markets_payload: dict,
    discovered_events: list,
) -> list:
    """
    Step 2 of the live flow: given the markets payload for the event
    ids discovered in step 1, produce normalized KenyanMatchOdds --
    football 1X2 only, rejecting any event whose 1x2 market isn't
    fully quoted.
    """

    events_by_id = {event["event_id"]: event for event in discovered_events}
    now = datetime.now(timezone.utc)
    results = []

    raw_entries = markets_payload.get("markets") if isinstance(markets_payload, dict) else None
    if not isinstance(raw_entries, list):
        raw_entries = []

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue

        event_id = entry.get("eventId")
        meta = events_by_id.get(event_id)
        if meta is None:
            continue

        market_1x2 = None
        for market in entry.get("markets") or []:
            if isinstance(market, dict) and market.get("id") == LIVE_1X2_MARKET_ID:
                market_1x2 = market
                break

        if market_1x2 is None:
            continue

        home_odds, draw_odds, away_odds = _selection_odds(
            market_1x2.get("selections") or [],
            home_team=meta["home_team"],
            away_team=meta["away_team"],
        )

        if home_odds is None or draw_odds is None or away_odds is None:
            continue

        start_time = _parse_iso_utc(meta.get("kickoff_utc")) or now

        results.append(
            KenyanMatchOdds(
                bookmaker=SPORTPESA,
                competition=meta["competition"],
                sport="Football",
                market="1X2",
                home_team=meta["home_team"],
                away_team=meta["away_team"],
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                start_time=start_time,
                collected_at=now,
                event_id=str(event_id),
                status="LIVE",
                source="sportpesa_live",
            )
        )

    return results


def parse_todays_games(games_payload: list, *, reference_now=None) -> list:
    """
    Parses the (already odds-embedded) `/api/todays/1/games` prematch
    payload. Ignores non-football events and events not scheduled for
    today (Kenya local date).
    """

    now = datetime.now(timezone.utc)
    results = []

    if not isinstance(games_payload, list):
        games_payload = []

    for game in games_payload:
        if not isinstance(game, dict):
            continue

        sport = game.get("sport") or {}
        if not isinstance(sport, dict) or sport.get("id") != 1:
            continue

        competitors = game.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            continue
        if not all(isinstance(c, dict) for c in competitors):
            continue

        timestamp_ms = game.get("dateTimestamp")
        if timestamp_ms is None:
            continue

        start_time = unix_seconds_to_datetime(timestamp_ms / 1000)

        if not is_today_in_kenya(start_time, reference=reference_now or now):
            continue

        market_3way = None
        for market in game.get("markets") or []:
            if isinstance(market, dict) and market.get("id") == PREMATCH_1X2_MARKET_ID:
                market_3way = market
                break

        if market_3way is None:
            continue

        home_odds = draw_odds = away_odds = None
        for selection in market_3way.get("selections") or []:
            if not isinstance(selection, dict):
                continue
            short_name = selection.get("shortName")
            try:
                price = float(selection.get("odds"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue

            if short_name == "1":
                home_odds = price
            elif short_name == "X":
                draw_odds = price
            elif short_name == "2":
                away_odds = price

        if home_odds is None or draw_odds is None or away_odds is None:
            continue

        competition = (game.get("competition") or {}).get("name") or ""

        results.append(
            KenyanMatchOdds(
                bookmaker=SPORTPESA,
                competition=competition,
                sport="Football",
                market="1X2",
                home_team=competitors[0].get("name"),
                away_team=competitors[1].get("name"),
                home_odds=home_odds,
                draw_odds=draw_odds,
                away_odds=away_odds,
                start_time=start_time,
                collected_at=now,
                event_id=str(game.get("id")),
                status="PREMATCH",
                source="sportpesa_prematch",
            )
        )

    return results
