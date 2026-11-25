"""Kolay91 live 1X2 adapter.

getMaclar keeps the prematch field names. The live/upcoming endpoint is
mapped into that same shape, then parsed by the prematch 1X2 functions
with feed_type=live. Prematch rows are not rewritten.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from parsers.kolay90_prematch.fetch import ENDPOINT, LIVE_UPCOMING_ENDPOINT
from parsers.kolay90_prematch.parser import (
    parse_live_payload,
    unwrap_events,
)

GETMACLAR = "getMaclar"
LIVE_UPCOMING = "live_upcoming"
ENDPOINTS = {
    GETMACLAR: ENDPOINT,
    LIVE_UPCOMING: LIVE_UPCOMING_ENDPOINT,
}
POLL_INTERVAL_SECONDS = 5.0

_HOME_KEYS = ("ev_sahibi", "home", "homeTeam", "home_team", "homeName", "evSahibi")
_AWAY_KEYS = ("deplasman", "away", "awayTeam", "away_team", "awayName")
_ID_KEYS = ("_id", "id", "eventId", "event_id", "matchId", "macId")
_ONE_X_TWO_NAMES = {"1x2", "ms", "match result", "mac sonucu", "maç sonucu", "1x2 result"}


def _first(item: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _odds_from_item(item: dict) -> dict | None:
    oranlar = item.get("oranlar")
    if isinstance(oranlar, dict) and all(key in oranlar for key in ("1", "0", "2")):
        return {"1": oranlar["1"], "0": oranlar["0"], "2": oranlar["2"]}
    for key in ("odds", "prices", "price"):
        odds = item.get(key)
        if not isinstance(odds, dict):
            continue
        if all(name in odds for name in ("1", "0", "2")):
            return {"1": odds["1"], "0": odds["0"], "2": odds["2"]}
        home = _first(odds, ("home", "1", "homeOdds"))
        draw = _first(odds, ("draw", "0", "drawOdds", "x"))
        away = _first(odds, ("away", "2", "awayOdds"))
        if home not in (None, "") and draw not in (None, "") and away not in (None, ""):
            return {"1": home, "0": draw, "2": away}
    markets = item.get("markets")
    if isinstance(markets, list):
        for market in markets:
            if not isinstance(market, dict):
                continue
            name = str(market.get("name") or market.get("market") or "").strip().casefold()
            if name and name not in _ONE_X_TWO_NAMES:
                continue
            selections = market.get("selections") or market.get("odds") or market.get("outcomes")
            if isinstance(selections, dict):
                found = _odds_from_item({"odds": selections})
                if found is not None:
                    return found
            if isinstance(selections, list):
                mapped = {}
                for selection in selections:
                    if not isinstance(selection, dict):
                        continue
                    label = str(selection.get("name") or selection.get("key") or "").strip().casefold()
                    price = selection.get("odds") or selection.get("price") or selection.get("value")
                    if label in {"1", "home", "ev sahibi"}:
                        mapped["1"] = price
                    elif label in {"0", "x", "draw", "beraberlik"}:
                        mapped["0"] = price
                    elif label in {"2", "away", "deplasman"}:
                        mapped["2"] = price
                if all(key in mapped and mapped[key] not in (None, "") for key in ("1", "0", "2")):
                    return mapped
    return None


def _zaman(item: dict) -> dict | None:
    zaman = item.get("zaman")
    if isinstance(zaman, dict) and zaman.get("sec") not in (None, ""):
        return zaman
    if isinstance(zaman, (int, float)):
        return {"sec": zaman}
    raw = _first(item, ("start", "startTime", "start_time", "date", "kickoff"))
    if isinstance(raw, (int, float)):
        return {"sec": raw}
    if isinstance(raw, str):
        text = raw.strip()
        if text.replace(".", "", 1).isdigit():
            return {"sec": float(text)}
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return {"sec": parsed.timestamp()}
    return None


def coerce_live_event(item: Any) -> dict | None:
    """Map one bookmaker row onto the getMaclar event the prematch parser reads."""
    if not isinstance(item, dict):
        return None
    if "ev_sahibi" in item and isinstance(item.get("oranlar"), dict):
        return item
    home = _first(item, _HOME_KEYS)
    away = _first(item, _AWAY_KEYS)
    event_id = _first(item, _ID_KEYS)
    odds = _odds_from_item(item)
    if not home or not away or event_id in (None, "") or odds is None:
        return None
    coerced = {
        "_id": event_id,
        "ev_sahibi": home,
        "deplasman": away,
        "oranlar": odds,
        "lig_id": item.get("lig_id") if item.get("lig_id") is not None else item.get("leagueId") or item.get("competitionId"),
        "code": item.get("code"),
        "zs": item.get("zs") or item.get("status") or item.get("minute") or "",
    }
    sport = item.get("spor") or item.get("sport")
    if sport not in (None, ""):
        coerced["spor"] = sport
    zaman = _zaman(item)
    if zaman is not None:
        coerced["zaman"] = zaman
    return coerced


def adapt_upcoming_payload(payload: Any) -> Any:
    """Return a getMaclar-shaped payload. Native rows pass through."""
    if isinstance(payload, dict) and isinstance(payload.get("maclar"), (dict, list)):
        return payload
    events = unwrap_events(payload)
    if events and all("ev_sahibi" in item and "oranlar" in item for item in events):
        return payload
    coerced = []
    for item in events:
        row = coerce_live_event(item)
        if row is not None:
            coerced.append(row)
    leagues = payload.get("ligler") if isinstance(payload, dict) else None
    return {"ligler": leagues or {}, "maclar": coerced}


def parse_endpoint_payload(name: str, payload: Any, collected_at: datetime | None = None, now: datetime | None = None):
    if name == LIVE_UPCOMING:
        payload = adapt_upcoming_payload(payload)
        return parse_live_payload(payload, collected_at, allow_upcoming=True, now=now)
    return parse_live_payload(payload, collected_at, allow_upcoming=False, now=now)


def diagnose(raw: dict, event_count: int, parsed_count: int) -> str:
    """Name the outcome without treating an empty body as a fresh odds update."""
    if raw.get("error"):
        return "network"
    status = raw.get("status")
    if status == 429:
        return "rate_limited"
    if raw.get("cloudflare") or (raw.get("looks_html") and not raw.get("json")):
        return "invalid"
    if raw.get("unauthenticated") or status in (401, 403):
        return "invalid"
    if not raw.get("json"):
        return "invalid"
    if parsed_count > 0:
        return "ok"
    if event_count > 0:
        return "parse_failure"
    return "no_live_events"


def retry_after_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


class PollSlot:
    def __init__(self, interval: float):
        self.in_flight = False
        self.next_monotonic = 0.0
        self.backoff = interval


def claim_due(slots: dict[str, PollSlot], now: float) -> str | None:
    """One due endpoint. A slot already in flight is not claimed again."""
    due = [
        name
        for name, slot in slots.items()
        if not slot.in_flight and now >= slot.next_monotonic
    ]
    if not due:
        return None
    return min(due, key=lambda name: (slots[name].next_monotonic, name))


def schedule_after(slot: PollSlot, now: float, interval: float, diagnosis: str, retry_after: float | None) -> None:
    if diagnosis in {"ok", "no_live_events"}:
        slot.backoff = interval
        slot.next_monotonic = now + interval
        return
    if diagnosis == "rate_limited":
        wait = retry_after if retry_after and retry_after > 0 else slot.backoff
        slot.next_monotonic = now + wait
        slot.backoff = min(max(slot.backoff * 2, interval), 60.0)
        return
    slot.next_monotonic = now + slot.backoff
    slot.backoff = min(max(slot.backoff * 2, interval), 30.0)


def merge_matches(rows: list) -> list:
    """One live 1X2 row per fixture. The newer collection wins."""
    chosen = {}
    for match in rows:
        key = (match.home_team, match.away_team, match.market, match.start_time)
        current = chosen.get(key)
        if current is None or match.collected_at >= current.collected_at:
            chosen[key] = match
    return list(chosen.values())
