"""Kolay90 prematch 1X2 parser.

Isolated from parsers/kolay90_parser.py (simulator shape) and from
live/prematch production feeds. Does not modify models.match.

Mapping is explicit:
  oranlar["1"] = HOME
  oranlar["0"] = DRAW
  oranlar["2"] = AWAY

An event is accepted only when all three keys exist and parse as
floats. Missing prices are never invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from models.match import MatchOdds

BOOKMAKER = "kolay90"
SPORT = "football"
MARKET = "1X2"
FEED = "prematch"
UNAUTH_MARKER = "Lütfen Tekrar Giriş Yapınız"
SPORT_KEYS = ("spor", "sport", "brans", "dal", "sport_name", "sportName", "sportId")
FOOTBALL_NAMES = {"futbol", "football", "soccer"}
NON_FOOTBALL = {"basketbol", "basketball", "tenis", "tennis", "voleybol", "voleyball"}


@dataclass(frozen=True)
class Kolay90PrematchOdds:
    """Experiment-local record. Wraps production MatchOdds plus IDs."""

    match: MatchOdds
    event_id: str
    bookmaker_code: str | None
    raw_home: str
    raw_draw: str
    raw_away: str

    @property
    def home_team(self) -> str:
        return self.match.home_team

    @property
    def away_team(self) -> str:
        return self.match.away_team

    @property
    def home_odds(self) -> float:
        return self.match.home_odds

    @property
    def draw_odds(self) -> float:
        return self.match.draw_odds

    @property
    def away_odds(self) -> float:
        return self.match.away_odds


def is_unauthenticated(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("hata") is True:
        return True
    message = str(payload.get("mesaj") or "")
    return UNAUTH_MARKER in message


def unwrap_events(payload: Any) -> list[dict]:
    if is_unauthenticated(payload):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("maclar", "matches", "data", "result", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if payload and all(isinstance(v, dict) for v in payload.values()):
        sample = next(iter(payload.values()))
        if "ev_sahibi" in sample or "oranlar" in sample:
            return [v for v in payload.values() if isinstance(v, dict)]
    return []


def oranlar_keys(item: dict) -> set[str]:
    oranlar = item.get("oranlar")
    if not isinstance(oranlar, dict):
        return set()
    present = set()
    for key in ("1", "0", "2"):
        value = oranlar.get(key)
        if value not in (None, ""):
            present.add(key)
    return present


def count_oranlar(events: list[dict]) -> dict[str, int]:
    any_price = 0
    all_three = 0
    for item in events:
        keys = oranlar_keys(item)
        if keys:
            any_price += 1
        if keys >= {"1", "0", "2"}:
            all_three += 1
    return {
        "with_any_1x2": any_price,
        "with_all_1x2": all_three,
    }


def extract_1x2(item: dict) -> tuple[str, str, str] | None:
    oranlar = item.get("oranlar")
    if not isinstance(oranlar, dict):
        return None
    if not all(key in oranlar for key in ("1", "0", "2")):
        return None
    home, draw, away = oranlar["1"], oranlar["0"], oranlar["2"]
    if home in (None, "") or draw in (None, "") or away in (None, ""):
        return None
    return str(home), str(draw), str(away)


def start_time_from_event(item: dict) -> datetime | None:
    zaman = item.get("zaman")
    sec = None
    if isinstance(zaman, dict):
        sec = zaman.get("sec")
    elif isinstance(zaman, (int, float)):
        sec = zaman
    if sec is None:
        return None
    try:
        value = float(sec)
    except (TypeError, ValueError):
        return None
    if value > 10_000_000_000:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _sport_label(item: dict) -> str | None:
    for key in SPORT_KEYS:
        value = item.get(key)
        if value is None or value == "":
            continue
        return str(value).strip().lower()
    return None


def is_football_event(item: dict) -> bool:
    label = _sport_label(item)
    if label is None:
        return True
    if label in NON_FOOTBALL:
        return False
    return label in FOOTBALL_NAMES


def parse_event(item: Any, collected_at: datetime | None = None) -> Kolay90PrematchOdds | None:
    if not isinstance(item, dict):
        return None
    event_id = item.get("_id")
    if event_id in (None, ""):
        return None
    if not is_football_event(item):
        return None
    home_team = item.get("ev_sahibi")
    away_team = item.get("deplasman")
    if not home_team or not away_team:
        return None
    raw = extract_1x2(item)
    if raw is None:
        return None
    try:
        home = float(raw[0])
        draw = float(raw[1])
        away = float(raw[2])
    except (TypeError, ValueError):
        return None
    start = start_time_from_event(item)
    if start is None:
        return None
    collected = collected_at or datetime.now(timezone.utc)
    lig_id = item.get("lig_id")
    code = item.get("code")
    match = MatchOdds(
        bookmaker=BOOKMAKER,
        competition=str(lig_id) if lig_id is not None else "",
        sport=SPORT,
        market=MARKET,
        home_team=str(home_team),
        away_team=str(away_team),
        home_odds=home,
        draw_odds=draw,
        away_odds=away,
        start_time=start,
        collected_at=collected,
        feed_type=FEED,
        tournament_id=str(lig_id) if lig_id is not None else None,
    )
    return Kolay90PrematchOdds(
        match=match,
        event_id=str(event_id),
        bookmaker_code=str(code) if code is not None else None,
        raw_home=raw[0],
        raw_draw=raw[1],
        raw_away=raw[2],
    )


def parse_payload(payload: Any, collected_at: datetime | None = None) -> list[Kolay90PrematchOdds]:
    by_id: dict[str, Kolay90PrematchOdds] = {}
    for item in unwrap_events(payload):
        parsed = parse_event(item, collected_at)
        if parsed is None:
            continue
        by_id[parsed.event_id] = parsed
    return list(by_id.values())


def validate_against_raw(item: dict, parsed: Kolay90PrematchOdds) -> list[str]:
    raw = extract_1x2(item)
    if raw is None:
        return ["missing raw 1X2"]
    failures = []
    for label, raw_value, parsed_value in (
        ("HOME", raw[0], parsed.home_odds),
        ("DRAW", raw[1], parsed.draw_odds),
        ("AWAY", raw[2], parsed.away_odds),
    ):
        try:
            expected = float(raw_value)
        except (TypeError, ValueError):
            failures.append(f"{label} raw {raw_value!r} is not a float")
            continue
        if parsed_value != expected:
            failures.append(
                f"{label} raw={raw_value!r} parsed={parsed_value!r} expected={expected!r}"
            )
    return failures
