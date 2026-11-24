"""OnWin live snapshot sent from the local Chrome collector.

The file holds MatchOdds fields only. It never stores cookies, tokens
from the sportsbook, or browser-profile data. A newer snapshot replaces
the previous one. The ZenRows OnWin worker is not involved.
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from models.match import MatchOdds

ROOT = Path(__file__).resolve().parents[2]
BOOKMAKER = "OnWin"


class IngestRejected(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


def max_age_seconds() -> float:
    try:
        return float(os.getenv("MAX_ODDS_AGE_SECONDS", "30"))
    except ValueError:
        return 30.0


def snapshot_path() -> Path:
    raw = (os.environ.get("ONWIN_REMOTE_SNAPSHOT") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "runtime" / "onwin_remote_snapshot.json"


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def match_to_payload(match: MatchOdds) -> dict:
    return {
        "bookmaker": BOOKMAKER,
        "competition": match.competition,
        "sport": match.sport,
        "market": match.market,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "home_odds": match.home_odds,
        "draw_odds": match.draw_odds,
        "away_odds": match.away_odds,
        "start_time": _iso(match.start_time),
        "collected_at": _iso(match.collected_at),
        "feed_type": "live",
    }


def match_from_payload(row: dict, now: datetime) -> MatchOdds:
    if not isinstance(row, dict):
        raise IngestRejected(400, "match row is not an object")
    bookmaker = str(row.get("bookmaker") or "").strip().lower()
    if bookmaker != "onwin":
        raise IngestRejected(400, "only onwin live rows are accepted")
    feed_type = str(row.get("feed_type") or "live").strip().lower()
    if feed_type != "live":
        raise IngestRejected(400, "only live rows are accepted")
    start = _parse_time(row.get("start_time"))
    collected = _parse_time(row.get("collected_at"))
    if start is None or collected is None:
        raise IngestRejected(400, "match timestamps are missing")
    # Receipt time is the VPS clock. The PC clock is not compared here:
    # a difference of more than MAX_ODDS_AGE_SECONDS was rejecting every
    # live batch with HTTP 409 before the engine ever saw it.
    try:
        home = float(row["home_odds"])
        draw = float(row["draw_odds"])
        away = float(row["away_odds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestRejected(400, "match odds are missing") from exc
    return MatchOdds(
        bookmaker=BOOKMAKER,
        competition=str(row.get("competition") or ""),
        sport=str(row.get("sport") or "football"),
        market=str(row.get("market") or "1X2"),
        home_team=str(row.get("home_team") or ""),
        away_team=str(row.get("away_team") or ""),
        home_odds=home,
        draw_odds=draw,
        away_odds=away,
        start_time=start,
        collected_at=collected,
        feed_type="live",
    )


def _read() -> dict | None:
    path = snapshot_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write(payload: dict) -> None:
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _authorized(header: str) -> bool:
    expected = (os.environ.get("ONWIN_INGEST_TOKEN") or "").strip()
    if not expected:
        raise IngestRejected(503, "ingest token is not configured")
    offered = (header or "").strip()
    if offered.lower().startswith("bearer "):
        offered = offered[7:].strip()
    if not offered:
        return False
    return hmac.compare_digest(offered.encode("utf-8"), expected.encode("utf-8"))


def _store_body(body: dict, current_time: datetime) -> dict:
    if not isinstance(body, dict):
        raise IngestRejected(400, "body must be an object")
    rows = body.get("matches")
    if not rows:
        return {"accepted": False, "reason": "no matches"}
    if not isinstance(rows, list):
        raise IngestRejected(400, "matches must be a list")
    if len(rows) > 20000:
        raise IngestRejected(413, "too many matches")
    parsed = [match_from_payload(row, current_time) for row in rows]
    received = [
        MatchOdds(
            bookmaker=match.bookmaker,
            competition=match.competition,
            sport=match.sport,
            market=match.market,
            home_team=match.home_team,
            away_team=match.away_team,
            home_odds=match.home_odds,
            draw_odds=match.draw_odds,
            away_odds=match.away_odds,
            start_time=match.start_time,
            collected_at=current_time,
            feed_type="live",
        )
        for match in parsed
    ]
    previous = _read()
    previous_collected = _parse_time((previous or {}).get("collected_at"))
    if previous_collected is not None and current_time <= previous_collected:
        return {"accepted": False, "reason": "not_newer"}
    stored = {
        "collected_at": _iso(current_time),
        "received_at": _iso(current_time),
        "count": len(received),
        "matches": [match_to_payload(match) for match in received],
    }
    _write(stored)
    return {"accepted": True, "count": len(parsed), "collected_at": stored["collected_at"]}


def accept_remote_snapshot(body: dict, authorization: str, now: datetime | None = None) -> dict:
    """Store a fresh OnWin live snapshot sent over HTTP."""
    if not isinstance(body, dict):
        raise IngestRejected(400, "body must be an object")
    if not _authorized(authorization):
        raise IngestRejected(401, "unauthorized")
    return _store_body(body, now or datetime.now(timezone.utc))


def store_local_snapshot(matches, now: datetime | None = None) -> dict:
    """Write live odds from a collector on this machine. No ingest token."""
    current_time = now or datetime.now(timezone.utc)
    if not matches:
        return {"accepted": False, "reason": "no matches"}
    return _store_body(
        {"matches": [match_to_payload(match) for match in matches]},
        current_time,
    )


def load_fresh_matches(now: datetime | None = None) -> list[MatchOdds] | None:
    payload = _read()
    if not payload:
        return None
    current_time = now or datetime.now(timezone.utc)
    collected = _parse_time(payload.get("collected_at"))
    if collected is None:
        return None
    age = (current_time - collected).total_seconds()
    if age < -30 or age > max_age_seconds():
        return None
    rows = payload.get("matches")
    if not isinstance(rows, list) or not rows:
        return None
    return [match_from_payload(row, current_time) for row in rows]


def remote_collection_age(now: datetime | None = None) -> float | None:
    payload = _read()
    if not payload:
        return None
    current_time = now or datetime.now(timezone.utc)
    collected = _parse_time(payload.get("collected_at"))
    if collected is None:
        return None
    age = (current_time - collected).total_seconds()
    if age < -30 or age > max_age_seconds():
        return None
    return age


def live_feed(now: datetime | None = None) -> dict | None:
    """Fresh OnWin rows for one engine tick, or None when the PC snapshot is stale."""
    matches = load_fresh_matches(now)
    if not matches:
        return None
    age = remote_collection_age(now)
    if age is None:
        return None
    current = now or datetime.now(timezone.utc)
    return {
        "matches": matches,
        "age": age,
        "last_update_at": current.timestamp() - age,
        "event_count": len(matches),
    }
