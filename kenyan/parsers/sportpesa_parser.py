"""
SportPesa parser.

RECONNAISSANCE FINDINGS (live-verified against the real API on
2026-08-30; see kenyan/fixtures/sportpesa_*.json for the captured,
trimmed payloads used by this module's tests):

- `https://www.ke.sportpesa.com/...` from this client returns HTTP 403
  Access Denied HTML and sets no cookies. That is a source failure.
  This module does not bypass it and does not reuse ZenRows.

- `https://www.sportpesa.com/...` serves the same API paths. A normal
  GET of the public homepage stores the site's own cookies on the
  session; the catalogue and markets calls then return JSON. All
  fixtures and the worker's default base URL use this host.

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

- PREMATCH catalogue: `/api/todays/1/games?type=prematch&section=today&...`
  returns today's football fixtures. `pag_min` is the 1-based item
  index and `pag_count` is the page size (15 in the site's own
  requests). Responses are HTTP 206 with `Content-Range: start-end/total`
  (0-based, inclusive). The next `pag_min` is `end + 2`. A `page`
  query parameter is ignored. The body is a JSON array even when
  `Content-Type` says `text/html`.

- Embedded markets on that list are only 1X2 (market id 10, name
  "1X2" or "3 Way", `shortName` 1/X/2). Totals are not embedded.

- PREMATCH markets: `/api/games/markets?games=<prematch ids>&markets=10,52-2.5`.
  `markets=10` is 1X2 (Home/Draw/Away, shortName 1/X/2). `markets=52-2.5`
  is "Total Goals Over/Under - Full Time" at line 2.5 (shortName OV/UN).
  `markets=52` without a line returns empty selections. This is a
  different payload from LIVE `/api/live/event/markets` (market id 194).
  Event ids must come from the prematch catalogue, not the live feed.
"""
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from engine.normalizer import TeamNameNormalizer
from kenyan.config import SPORTPESA
from kenyan.date_utils import is_today_in_kenya, unix_seconds_to_datetime
from kenyan.log import log_parse
from kenyan.markets import (
    FAMILY_TOTAL,
    FAMILY_WINNER,
    MARKET_MATCH_WINNER,
    MARKET_TOTAL,
    PERIOD_FULL_MATCH,
    finalize_match,
)
from kenyan.models import KenyanMatchOdds
from kenyan.odds import parse_decimal_odds
from resources.aliases import TEAM_ALIASES

LIVE_1X2_MARKET_ID = 194
PREMATCH_1X2_MARKET_ID = 10
PREMATCH_TOTAL_MARKET_ID = 52
# Verified prematch markets query. 10 is 1X2. 52-2.5 is the full-time
# goals total; the line has to be part of the query or selections are empty.
PREMATCH_MARKETS_QUERY = "10,52-2.5"
LIVE_1X2_MARKET_NAMES = frozenset({"1x2", "3 way", "3-way", "match winner"})
PREMATCH_1X2_MARKET_NAMES = frozenset({"3 way", "3-way", "1x2", "match winner"})
_CONTENT_RANGE_RE = re.compile(r"(\d+)\s*-\s*(\d+)\s*/\s*(\d+)")

SPORTPESA_BASE_URL = "https://www.sportpesa.com"

_NORMALIZER = TeamNameNormalizer()
_DRAW_NAMES = frozenset({"draw", "x", "tie", "beraberlik"})


def _event_id_key(value) -> str:
    if value is None:
        return ""
    return str(value)


def _as_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_open_selection(status) -> bool:
    if status is None or status == "":
        return True
    return str(status).strip().lower() == "open"


def _is_live_1x2_market(market: dict) -> bool:
    if _as_int(market.get("id")) == LIVE_1X2_MARKET_ID:
        return True
    name = str(market.get("name") or market.get("shortName") or "").strip().lower()
    return name in LIVE_1X2_MARKET_NAMES


def _is_prematch_1x2_market(market: dict) -> bool:
    if _as_int(market.get("id")) == PREMATCH_1X2_MARKET_ID:
        return True
    name = str(market.get("name") or market.get("shortName") or "").strip().lower()
    return name in PREMATCH_1X2_MARKET_NAMES


def _canonical_team(name: str) -> str:
    value = _NORMALIZER.normalize(name or "")
    if not value:
        return ""
    aliased = TEAM_ALIASES.get(value, value)
    return TEAM_ALIASES.get(aliased, aliased)


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


def build_todays_games_url(*, page_min: int = 1, page_count: int = 15) -> str:
    return (
        f"{SPORTPESA_BASE_URL}/api/todays/1/games"
        f"?type=prematch&section=today&markets_layout=multiple"
        f"&o=startTime&pag_count={page_count}&pag_min={page_min}"
    )


def build_prematch_markets_url(event_ids) -> str:
    """PREMATCH `/api/games/markets` for ids taken from the prematch catalogue."""
    ids = ",".join(
        event_id
        for event_id in (_event_id_key(value) for value in event_ids)
        if event_id
    )
    games = quote(ids, safe=",")
    markets = quote(PREMATCH_MARKETS_QUERY, safe=",-")
    return f"{SPORTPESA_BASE_URL}/api/games/markets?games={games}&markets={markets}"


def parse_content_range(value):
    """
    Parse SportPesa `Content-Range: start-end/total`.

    start/end are 0-based and inclusive. Returns None when the header
    is missing or not in that form. Does not invent page/offset/skip.
    """
    if value is None or value == "":
        return None
    match = _CONTENT_RANGE_RE.search(str(value))
    if not match:
        return None
    start, end, total = (int(match.group(index)) for index in range(1, 4))
    if end < start or total < 0:
        return None
    return start, end, total


def looks_like_live_markets_payload(payload) -> bool:
    """LIVE `/api/live/event/markets` shape. Not a prematch markets document."""
    if not isinstance(payload, dict):
        return False
    rows = payload.get("markets")
    if not isinstance(rows, list) or not rows:
        return False
    first = rows[0]
    return isinstance(first, dict) and "eventId" in first and "markets" in first


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
        if not isinstance(sport, dict) or _as_int(sport.get("id")) != 1:
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
                "home_team_id": _event_id_key(competitors[0].get("id")),
                "away_team_id": _event_id_key(competitors[1].get("id")),
                "competition": (event.get("tournament") or {}).get("name") or "",
                "league_id": _event_id_key((event.get("tournament") or {}).get("id")),
                "kickoff_utc": event.get("kickoffTimeUTC"),
                "external_id": _event_id_key(event.get("externalId")),
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
    live sample shows SportPesa does not guarantee ordering). Falls
    back to shortName 1/X/2 when names differ by FC/suffix only.
    A selection whose status isn't "Open" is treated as unavailable.
    """

    home_price = draw_price = away_price = None

    if not isinstance(selections, list):
        return home_price, draw_price, away_price

    home_key = _canonical_team(home_team)
    away_key = _canonical_team(away_team)

    for selection in selections:
        if not isinstance(selection, dict):
            continue

        status = selection.get("status")
        if not _is_open_selection(status):
            continue

        price = parse_decimal_odds(selection.get("odds"))
        if price is None:
            continue

        name = (selection.get("name") or "").strip()
        short_name = (selection.get("shortName") or "").strip()
        name_key = _canonical_team(name)
        lowered = name.lower()

        if short_name == "1" or name == "1" or (home_key and name_key == home_key):
            home_price = price
        elif short_name == "2" or name == "2" or (away_key and name_key == away_key):
            away_price = price
        elif short_name == "X" or name == "X" or lowered in _DRAW_NAMES:
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

    events_by_id = {
        _event_id_key(event["event_id"]): event for event in discovered_events
    }
    now = datetime.now(timezone.utc)
    results = []

    raw_entries = markets_payload.get("markets") if isinstance(markets_payload, dict) else None
    if not isinstance(raw_entries, list):
        raw_entries = []

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue

        event_id = _event_id_key(entry.get("eventId"))
        meta = events_by_id.get(event_id)
        if meta is None:
            log_parse(
                SPORTPESA,
                event=str(entry.get("eventId") or ""),
                status="rejected",
                market="MATCH_WINNER",
                event_id=event_id,
                reason="MATCH_IDENTITY_MISMATCH",
            )
            continue

        market_1x2 = None
        for market in entry.get("markets") or []:
            if isinstance(market, dict) and _is_live_1x2_market(market):
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
            log_parse(
                SPORTPESA,
                event=f"{meta['home_team']} vs {meta['away_team']}",
                status="rejected",
                market="MATCH_WINNER",
                event_id=event_id,
                reason="MARKET_IDENTITY_MISMATCH",
            )
            continue

        start_time = _parse_iso_utc(meta.get("kickoff_utc")) or now
        market_id = _event_id_key(market_1x2.get("id"))

        match = KenyanMatchOdds(
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
            event_id=event_id,
            cluster_id=f"m{market_id}",
            market_id=market_id,
            parent_event_id=event_id,
            home_team_id=meta.get("home_team_id") or "",
            away_team_id=meta.get("away_team_id") or "",
            league_id=meta.get("league_id") or "",
            status="LIVE",
            source="sportpesa_live",
        )
        log_parse(
            SPORTPESA,
            event=f"{match.home_team} vs {match.away_team}",
            status="parsed",
            market="MATCH_WINNER",
            selection="HOME",
            event_id=match.event_id,
            market_id=match.market_id,
        )
        results.append(match)

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
        if not isinstance(sport, dict) or _as_int(sport.get("id")) != 1:
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

        event_id = _event_id_key(game.get("id"))
        home_name = competitors[0].get("name")
        away_name = competitors[1].get("name")
        if not is_today_in_kenya(start_time, reference=reference_now or now):
            log_parse(
                SPORTPESA,
                event=f"{home_name} vs {away_name}",
                status="rejected",
                market="MATCH_WINNER",
                event_id=event_id,
                reason="NOT_TODAY_KENYA",
            )
            continue

        market_3way = None
        for market in game.get("markets") or []:
            if isinstance(market, dict) and _is_prematch_1x2_market(market):
                market_3way = market
                break

        if market_3way is None:
            log_parse(
                SPORTPESA,
                event=f"{home_name} vs {away_name}",
                status="rejected",
                market="MATCH_WINNER",
                event_id=event_id,
                reason="NO_MATCH_WINNER_MARKET",
            )
            continue

        home_odds = draw_odds = away_odds = None
        for selection in market_3way.get("selections") or []:
            if not isinstance(selection, dict):
                continue
            short_name = (selection.get("shortName") or "").strip()
            name = (selection.get("name") or "").strip()
            price = parse_decimal_odds(selection.get("odds"))
            if price is None:
                continue

            if short_name == "1" or name == "1":
                home_odds = price
            elif short_name == "X" or name == "X":
                draw_odds = price
            elif short_name == "2" or name == "2":
                away_odds = price

        if home_odds is None or draw_odds is None or away_odds is None:
            log_parse(
                SPORTPESA,
                event=f"{home_name} vs {away_name}",
                status="rejected",
                market="MATCH_WINNER",
                event_id=event_id,
                reason="INCOMPLETE_1X2",
            )
            continue

        competition = (game.get("competition") or {}).get("name") or ""
        market_id = _event_id_key(market_3way.get("id"))

        match = KenyanMatchOdds(
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
            event_id=event_id,
            cluster_id=f"m{market_id}",
            market_id=market_id,
            parent_event_id=event_id,
            home_team_id=_event_id_key(competitors[0].get("id")),
            away_team_id=_event_id_key(competitors[1].get("id")),
            league_id=_event_id_key((game.get("competition") or {}).get("id")),
            status="PREMATCH",
            source="sportpesa_prematch",
        )
        log_parse(
            SPORTPESA,
            event=f"{match.home_team} vs {match.away_team}",
            status="parsed",
            market="MATCH_WINNER",
            selection="HOME",
            event_id=match.event_id,
            market_id=match.market_id,
        )
        results.append(match)

    return results


def _reject(event, event_id, market, reason):
    log_parse(
        SPORTPESA,
        event=event,
        status="rejected",
        market=market,
        event_id=event_id,
        reason=reason,
    )


def _prematch_context(game, *, reference_now=None):
    """Football prematch game scheduled today in Kenya, or None."""
    if not isinstance(game, dict):
        return None
    sport = game.get("sport") or {}
    if not isinstance(sport, dict) or _as_int(sport.get("id")) != 1:
        return None
    competitors = game.get("competitors")
    if not isinstance(competitors, list) or len(competitors) != 2:
        return None
    if not all(isinstance(competitor, dict) for competitor in competitors):
        return None
    timestamp_ms = game.get("dateTimestamp")
    if timestamp_ms is None:
        return None
    start_time = unix_seconds_to_datetime(timestamp_ms / 1000)
    now = reference_now or datetime.now(timezone.utc)
    home_name = competitors[0].get("name") or ""
    away_name = competitors[1].get("name") or ""
    event_id = _event_id_key(game.get("id"))
    if not is_today_in_kenya(start_time, reference=now):
        return None
    return {
        "event_id": event_id,
        "home_name": home_name,
        "away_name": away_name,
        "home_team_id": _event_id_key(competitors[0].get("id")),
        "away_team_id": _event_id_key(competitors[1].get("id")),
        "competition": (game.get("competition") or {}).get("name") or "",
        "league_id": _event_id_key((game.get("competition") or {}).get("id")),
        "start_time": start_time,
        "label": f"{home_name} vs {away_name}",
    }


def _selection_price(selection):
    if not isinstance(selection, dict):
        return None, None
    if not _is_open_selection(selection.get("status")):
        return None, None
    short_name = (selection.get("shortName") or "").strip()
    name = (selection.get("name") or "").strip()
    raw = selection.get("odds")
    price = parse_decimal_odds(raw)
    if price is None and raw not in (None, ""):
        return short_name, "malformed"
    return (short_name, name, price), None


def _prices_by_role(selections, roles):
    """Map outcome role -> price. roles is shortName/name -> role."""
    found = {}
    malformed = False
    for selection in selections or []:
        parsed, flag = _selection_price(selection)
        if flag == "malformed":
            malformed = True
            continue
        if parsed is None:
            continue
        short_name, name, price = parsed
        if price is None:
            continue
        role = roles.get(short_name.upper()) or roles.get(name.strip().lower())
        if role and role not in found:
            found[role] = price
    return found, malformed


def _build_winner(context, market, now):
    prices, malformed = _prices_by_role(
        market.get("selections") or [],
        {
            "1": "home",
            "HOME": "home",
            "home": "home",
            "X": "draw",
            "DRAW": "draw",
            "draw": "draw",
            "2": "away",
            "AWAY": "away",
            "away": "away",
        },
    )
    event_id = context["event_id"]
    if malformed and not all(role in prices for role in ("home", "draw", "away")):
        _reject(context["label"], event_id, "MATCH_WINNER", "MALFORMED_ODDS")
    if not all(role in prices for role in ("home", "draw", "away")):
        return None
    market_id = _event_id_key(market.get("id")) or str(PREMATCH_1X2_MARKET_ID)
    match = KenyanMatchOdds(
        bookmaker=SPORTPESA,
        competition=context["competition"],
        sport="Football",
        market="1X2",
        home_team=context["home_name"],
        away_team=context["away_name"],
        home_odds=prices["home"],
        draw_odds=prices["draw"],
        away_odds=prices["away"],
        start_time=context["start_time"],
        collected_at=now,
        event_id=event_id,
        cluster_id=f"m{market_id}",
        market_id=market_id,
        parent_event_id=event_id,
        home_team_id=context["home_team_id"],
        away_team_id=context["away_team_id"],
        league_id=context["league_id"],
        status="PREMATCH",
        source="sportpesa_prematch",
        market_type=MARKET_MATCH_WINNER,
        period=PERIOD_FULL_MATCH,
        outcome_family=FAMILY_WINNER,
    )
    return finalize_match(match)


def _total_line(market, selections):
    values = []
    market_spec = market.get("specValue")
    if market_spec not in (None, "", 0, 0.0, "0", "0.0"):
        values.append(market_spec)
    for selection in selections:
        if not isinstance(selection, dict):
            continue
        spec = selection.get("specValue")
        if spec in (None, "", 0, 0.0, "0", "0.0"):
            continue
        values.append(spec)
    parsed = []
    for value in values:
        try:
            parsed.append(round(float(value), 2))
        except (TypeError, ValueError):
            return None
    if not parsed:
        return None
    if any(abs(item - parsed[0]) > 0.001 for item in parsed):
        return "mismatch"
    return parsed[0]


def _is_full_time_total(market) -> bool:
    if not isinstance(market, dict):
        return False
    if _as_int(market.get("id")) == LIVE_1X2_MARKET_ID:
        return False
    if _as_int(market.get("id")) != PREMATCH_TOTAL_MARKET_ID:
        return False
    name = str(market.get("name") or "").lower()
    if "full time" not in name and "fulltime" not in name:
        return False
    return "over" in name or "under" in name or "total" in name


def _build_total(context, market, now):
    selections = market.get("selections") or []
    if not selections:
        return None
    line = _total_line(market, selections)
    event_id = context["event_id"]
    if line == "mismatch" or line is None:
        _reject(context["label"], event_id, "TOTAL", "MARKET_IDENTITY_MISMATCH")
        return None
    prices, malformed = _prices_by_role(
        selections,
        {"OV": "over", "UN": "under"},
    )
    if "over" not in prices or "under" not in prices:
        for selection in selections:
            if not isinstance(selection, dict) or not _is_open_selection(selection.get("status")):
                continue
            name = (selection.get("name") or "").strip().lower()
            raw = selection.get("odds")
            price = parse_decimal_odds(raw)
            if price is None:
                if raw not in (None, ""):
                    malformed = True
                continue
            if name.startswith("over") and "over" not in prices:
                prices["over"] = price
            elif name.startswith("under") and "under" not in prices:
                prices["under"] = price
    if malformed and ("over" not in prices or "under" not in prices):
        _reject(context["label"], event_id, "TOTAL", "MALFORMED_ODDS")
    if "over" not in prices or "under" not in prices:
        _reject(context["label"], event_id, "TOTAL", "INCOMPLETE_TOTAL")
        return None
    market_id = _event_id_key(market.get("id")) or str(PREMATCH_TOTAL_MARKET_ID)
    match = KenyanMatchOdds(
        bookmaker=SPORTPESA,
        competition=context["competition"],
        sport="Football",
        market="over_under",
        home_team=context["home_name"],
        away_team=context["away_name"],
        home_odds=prices["over"],
        draw_odds=None,
        away_odds=prices["under"],
        start_time=context["start_time"],
        collected_at=now,
        event_id=event_id,
        cluster_id=f"m{market_id}:{line}",
        market_id=market_id,
        parent_event_id=event_id,
        home_team_id=context["home_team_id"],
        away_team_id=context["away_team_id"],
        league_id=context["league_id"],
        status="PREMATCH",
        source="sportpesa_prematch",
        line=line,
        market_type=MARKET_TOTAL,
        period=PERIOD_FULL_MATCH,
        outcome_family=FAMILY_TOTAL,
    )
    return finalize_match(match)


def assemble_prematch_matches(games, markets_payload=None, *, reference_now=None) -> list:
    """
    Join a prematch game list with `/api/games/markets`.

    Embedded 1X2 is kept when the markets document does not replace it.
    A LIVE markets document is ignored so live prices cannot be stored
    as prematch. Totals keep their line and never invent a draw.
    """
    now = datetime.now(timezone.utc)
    if not isinstance(games, list):
        games = []

    deduped = []
    seen = set()
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = _event_id_key(game.get("id"))
        if not event_id:
            competitors = game.get("competitors") or []
            label = ""
            if len(competitors) == 2 and all(isinstance(item, dict) for item in competitors):
                label = f"{competitors[0].get('name')} vs {competitors[1].get('name')}"
            _reject(label, "", "MATCH_WINNER", "MISSING_EVENT_ID")
            continue
        if event_id in seen:
            continue
        seen.add(event_id)
        deduped.append(game)

    winners = {}
    for match in parse_todays_games(deduped, reference_now=reference_now):
        winners[match.event_id] = finalize_match(match)

    if looks_like_live_markets_payload(markets_payload):
        _reject("", "", "MATCH_WINNER", "LIVE_PAYLOAD_REJECTED")
        return list(winners.values())

    if not isinstance(markets_payload, dict):
        return list(winners.values())

    known_ids = {_event_id_key(game.get("id")) for game in deduped}
    contexts = {}
    for game in deduped:
        context = _prematch_context(game, reference_now=reference_now)
        if context is not None:
            contexts[context["event_id"]] = context

    totals = []
    seen_totals = set()
    for raw_id, markets in markets_payload.items():
        event_id = _event_id_key(raw_id)
        if event_id not in known_ids:
            _reject(str(raw_id), event_id, "MATCH_WINNER", "MISSING_EVENT_ID")
            continue
        context = contexts.get(event_id)
        if context is None:
            continue
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            if _as_int(market.get("id")) == LIVE_1X2_MARKET_ID:
                _reject(context["label"], event_id, "MATCH_WINNER", "LIVE_MARKET_ON_PREMATCH")
                continue
            if _is_prematch_1x2_market(market):
                built = _build_winner(context, market, now)
                if built is not None:
                    winners[event_id] = built
                continue
            if not _is_full_time_total(market):
                continue
            built = _build_total(context, market, now)
            if built is None:
                continue
            key = (event_id, built.period, built.line)
            if key in seen_totals:
                continue
            seen_totals.add(key)
            totals.append(built)

    return list(winners.values()) + totals
