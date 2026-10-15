"""Serialize Kenyan MatchOdds and HTTP URLs for forensic export."""
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from kenyan.markets import kenyan_market_key, market_label, sport_key
from kenyan.matcher import KenyanEventMatcher, _start_minute_bucket

_MATCHER = KenyanEventMatcher()
_SECRET_QUERY_KEYS = {
    "token",
    "access_token",
    "auth",
    "authorization",
    "cookie",
    "session",
    "jwt",
    "api_key",
    "apikey",
    "password",
    "secret",
}


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat() + "Z"
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def sanitize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_KEYS:
            query.append((key, "<redacted>"))
        else:
            query.append((key, value))
    encoded = "&".join(f"{key}={value}" for key, value in query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded, ""))


def canonical_fixture_key(match) -> dict:
    home = _MATCHER.canonical_team(getattr(match, "home_team", "") or "")
    away = _MATCHER.canonical_team(getattr(match, "away_team", "") or "")
    sport = sport_key(match)
    bucket = _start_minute_bucket(getattr(match, "start_time", None))
    return {
        "sport": sport,
        "canonical_home": home or None,
        "canonical_away": away or None,
        "start_minute": bucket,
        "key": f"{sport}|{home}|{away}|{bucket}",
    }


def matchodds_record(match, *, snapshot_status="parsed", rejection_reason=None) -> dict:
    """Map actual KenyanMatchOdds attributes. Empty string is stored as-is."""
    fixture = canonical_fixture_key(match)
    market_parts = kenyan_market_key(match)
    return {
        "bookmaker": getattr(match, "bookmaker", None),
        "sport": getattr(match, "sport", None),
        "sport_key": fixture["sport"],
        "competition": getattr(match, "competition", None),
        "source_event_id": getattr(match, "event_id", None) or None,
        "parent_event_id": getattr(match, "parent_event_id", None) or None,
        "home_team": getattr(match, "home_team", None),
        "away_team": getattr(match, "away_team", None),
        "canonical_event_key": fixture["key"],
        "canonical_home": fixture["canonical_home"],
        "canonical_away": fixture["canonical_away"],
        "market": getattr(match, "market", None),
        "market_id": getattr(match, "market_id", None) or None,
        "cluster_id": getattr(match, "cluster_id", None) or None,
        "market_type": getattr(match, "market_type", None) or None,
        "market_label": market_label(match),
        "outcome_family": getattr(match, "outcome_family", None) or None,
        "period": getattr(match, "period", None),
        "line": getattr(match, "line", None),
        "home_odds": getattr(match, "home_odds", None),
        "draw_odds": getattr(match, "draw_odds", None),
        "away_odds": getattr(match, "away_odds", None),
        "home_team_id": getattr(match, "home_team_id", None) or None,
        "away_team_id": getattr(match, "away_team_id", None) or None,
        "league_id": getattr(match, "league_id", None) or None,
        "start_time": _iso(getattr(match, "start_time", None)),
        "collected_at": _iso(getattr(match, "collected_at", None)),
        "confirmed_at": _iso(getattr(match, "confirmed_at", None)),
        "status": getattr(match, "status", None),
        "source": getattr(match, "source", None),
        "side": getattr(match, "side", None),
        "market_identity": list(market_parts),
        "snapshot_status": snapshot_status,
        "rejection_reason": rejection_reason,
        "selection_ids": None,
        "selection_ids_note": "KenyanMatchOdds stores HOME/DRAW/AWAY (or OVER/UNDER) prices on one object; per-outcome source selection IDs are not retained on the model.",
    }


def classify_vzip_event(event: dict) -> str:
    if not isinstance(event, dict):
        return "not_an_object"
    if "eventGroups" in event:
        sport_id = (event.get("sport") or {}).get("id")
        home = (event.get("opponent1") or {}).get("fullName")
        away = (event.get("opponent2") or {}).get("fullName")
        start = event.get("startTs")
        event_id = event.get("id")
    else:
        sport_id = event.get("SI")
        home = event.get("O1")
        away = event.get("O2")
        start = event.get("S")
        event_id = event.get("I")
    if sport_id not in (1, 3, 4, 6):
        return "unsupported_sport"
    if not home or not away:
        return "missing_team_names"
    if (home or "").strip().lower() in {"home", "away"} and (
        away or ""
    ).strip().lower() in {"home", "away"}:
        return "placeholder_fixture"
    if start is None:
        return "missing_start_time"
    if event_id in (None, ""):
        return "missing_event_id"
    return "no_supported_market"


def classify_betika_event(row: dict) -> str:
    if not isinstance(row, dict):
        return "not_an_object"
    sport_id = str(row.get("sport_id") or "")
    sport_name = (row.get("sport_name") or "").strip().lower()
    supported_ids = {"14", "28", "30", "35"}
    supported_names = {"soccer", "football", "tennis", "basketball", "volleyball"}
    if sport_id not in supported_ids and sport_name not in supported_names:
        return "unsupported_sport"
    if not row.get("home_team") or not row.get("away_team"):
        return "missing_team_names"
    if not row.get("start_time"):
        return "missing_start_time"
    return "no_supported_market"


def classify_sportpesa_game(game: dict) -> str:
    if not isinstance(game, dict):
        return "not_an_object"
    sport = game.get("sport") or {}
    sport_id = sport.get("id") if isinstance(sport, dict) else None
    try:
        sport_id = int(sport_id)
    except (TypeError, ValueError):
        sport_id = None
    if sport_id != 1:
        return "unsupported_sport"
    competitors = game.get("competitors")
    if not isinstance(competitors, list) or len(competitors) != 2:
        return "missing_competitors"
    if game.get("dateTimestamp") is None:
        return "missing_start_time"
    return "not_today_or_no_1x2"
