"""OnWin prematch snapshot sent from the local Chrome collector.

Same token as the live ingest. The file holds MatchOdds fields only.
Receipt time is the VPS clock. The ZenRows prematch worker is not required.
"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from models.match import MatchOdds
from prematch.pipeline import PREMATCH_MAX_ODDS_AGE_SECONDS

ROOT = Path(__file__).resolve().parents[2]
BOOKMAKER = "OnWin"


class IngestRejected(Exception):
    def __init__(self, status_code: int, reason: str):
        super().__init__(reason)
        self.status_code = status_code
        self.reason = reason


def snapshot_path() -> Path:
    raw = (os.environ.get("ONWIN_PREMATCH_REMOTE_SNAPSHOT") or "").strip()
    if raw:
        return Path(raw)
    return ROOT / "runtime" / "onwin_prematch_remote_snapshot.json"


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
    payload = {
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
        "feed_type": "prematch",
    }
    if match.line is not None:
        payload["line"] = match.line
    return payload


def match_from_payload(row: dict, now: datetime) -> MatchOdds:
    del now
    if not isinstance(row, dict):
        raise IngestRejected(400, "match row is not an object")
    bookmaker = str(row.get("bookmaker") or "").strip().lower()
    if bookmaker != "onwin":
        raise IngestRejected(400, "only onwin prematch rows are accepted")
    feed_type = str(row.get("feed_type") or "").strip().lower()
    if feed_type != "prematch":
        raise IngestRejected(400, "only prematch rows are accepted")
    start = _parse_time(row.get("start_time"))
    collected = _parse_time(row.get("collected_at"))
    if start is None or collected is None:
        raise IngestRejected(400, "match timestamps are missing")
    try:
        home = float(row["home_odds"])
        draw = float(row["draw_odds"])
        away = float(row["away_odds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IngestRejected(400, "match odds are missing") from exc
    line = row.get("line")
    if line is not None:
        line = float(line)
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
        feed_type="prematch",
        line=line,
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
            feed_type="prematch",
            line=match.line,
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
    return {"accepted": True, "count": len(received), "collected_at": stored["collected_at"]}


def accept_remote_snapshot(body: dict, authorization: str, now: datetime | None = None) -> dict:
    if not isinstance(body, dict):
        raise IngestRejected(400, "body must be an object")
    if not _authorized(authorization):
        raise IngestRejected(401, "unauthorized")
    return _store_body(body, now or datetime.now(timezone.utc))


def store_local_snapshot(matches, now: datetime | None = None) -> dict:
    """Write prematch odds from a collector on this machine. No ingest token."""
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
    if age < -30 or age > PREMATCH_MAX_ODDS_AGE_SECONDS:
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
    if age < -30 or age > PREMATCH_MAX_ODDS_AGE_SECONDS:
        return None
    return age


def remote_is_fresh(now: datetime | None = None) -> bool:
    return load_fresh_matches(now) is not None


def prefer_remote_onwin(worker_matches, now: datetime | None = None) -> list:
    """Use a fresh PC prematch snapshot when one exists."""
    remote = load_fresh_matches(now)
    if remote is not None:
        return remote
    return list(worker_matches or [])
