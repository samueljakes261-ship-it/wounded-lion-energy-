"""
Per-event snapshot merge for Kenyan workers.

LIVE endpoints for 1xBet/22Bet/SportPesa are count/limit windows, not
guaranteed full catalogues. Replacing `self._matches = latest_poll`
therefore drops events that were merely off this page, which then
drops the corresponding arbitrage opportunities. This merge keeps
per-event last-seen timestamps and expires them using the feed's
stale window.

`collected_at` is the time those odds were last confirmed present in a
completed poll (restamped to poll-end for rows in that poll). Readers
must not restamp it again on every serve -- that would present stale
odds as current.

`acquired_seq` is the worker poll generation. A delayed older poll
cannot overwrite a newer snapshot even if it finishes later.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional


@dataclass
class MatchRecord:
    match: object
    last_seen: float
    acquired_seq: int = 0


def match_identity(match) -> str:
    """
    Stable per-bookmaker market identity. LIVE and PREMATCH stay
    distinct because `status` is part of the key. Bookmaker event ids
    are namespaced per bookmaker, so they are safe here (unlike cross-
    book matching, which never uses them).
    """

    bookmaker = getattr(match, "bookmaker", "") or ""
    status = getattr(match, "status", "") or ""
    market = getattr(match, "market", "") or ""
    event_id = getattr(match, "event_id", "") or ""
    period = getattr(match, "period", None) or ""
    line = getattr(match, "line", None)
    extra = ""
    if period and period != "FULL_MATCH":
        extra += f"|{period}"
    if line is not None:
        extra += f"|{line}"
    if event_id:
        return f"{bookmaker}|{status}|{event_id}|{market}{extra}"
    home = getattr(match, "home_team", "") or ""
    away = getattr(match, "away_team", "") or ""
    return f"{bookmaker}|{status}|{home}|{away}|{market}{extra}"


def merge_match_records(
    previous: Optional[Dict[str, MatchRecord]],
    incoming: Iterable,
    *,
    now: float,
    retention_seconds: float,
    acquired_seq: int = 0,
) -> Dict[str, MatchRecord]:
    """
    Update records present in `incoming`. Records missing from this
    poll are kept until `now - last_seen > retention_seconds`.
    An incoming row with a lower `acquired_seq` than the stored row
    is ignored so a delayed poll cannot overwrite newer odds.
    """

    records = dict(previous or {})
    seen = set()
    collected_at = datetime.fromtimestamp(now, tz=timezone.utc)

    for match in incoming:
        key = match_identity(match)
        existing = records.get(key)
        if existing is not None and existing.acquired_seq > acquired_seq:
            continue
        if hasattr(match, "collected_at"):
            match.collected_at = collected_at
        records[key] = MatchRecord(
            match=match,
            last_seen=now,
            acquired_seq=acquired_seq,
        )
        seen.add(key)

    expired = [
        key
        for key, record in records.items()
        if key not in seen and (now - record.last_seen) > retention_seconds
    ]
    for key in expired:
        del records[key]

    return records


def visible_matches(records: Optional[Dict[str, MatchRecord]], *, now: float, retention_seconds: float) -> list:
    if not records:
        return []
    return [
        record.match
        for record in records.values()
        if (now - record.last_seen) <= retention_seconds
    ]
