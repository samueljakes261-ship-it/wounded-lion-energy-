"""
Structured, opt-in odds tracing across the full data pipeline.

Purpose: let a human (or a test) compare a specific match's odds value
at every stage it passes through --

    RAW (as the bookmaker's response literally contains it)
    -> PARSED (after this project's parser/adapter builds a MatchOdds)
    -> ENGINE (after BestOddsSelector picks it as the best price)
    -> API/CACHE (the exact value written to cached_opportunities.json,
       which api.py returns byte-for-byte)

-- WITHOUT modifying the odds themselves anywhere. This module only
ever reads and prints/records values; it never changes them.

Disabled by default (ODDS_TRACE=1/true/yes to enable) so it costs a
single boolean check per call in normal operation, and NEVER logs
credentials, API keys, tokens, or any authentication material -- only
sport/team/market/odds/timestamps, i.e. exactly the same class of
information already printed by the engine's existing terminal status
lines (see collector.py).
"""

import os
import time
from collections import defaultdict, deque


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


TRACE_ENABLED = _env_flag("ODDS_TRACE")

# Bounded per-key history so a long-running process tracing a busy
# feed (e.g. Orbit) can't leak memory -- only the most recent
# observations per (bookmaker, event, market, side) are kept.
_MAX_HISTORY_PER_KEY = 20

_history: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=_MAX_HISTORY_PER_KEY))


def _key(bookmaker, home_team, away_team, market, side=None):
    return (bookmaker, home_team, away_team, market, side)


def record(
    stage: str,
    bookmaker: str,
    home_team: str,
    away_team: str,
    market: str,
    side: str | None,
    home_odds,
    draw_odds,
    away_odds,
    raw: dict | None = None,
):
    """
    Record one pipeline-stage observation of a match's odds.

    stage: free-form label -- "RAW"/"PARSED"/"ENGINE"/"API" are the
    ones the rest of this codebase uses, matching the pipeline
    diagram in HANDOFF.md / docs/ODDS_PIPELINE.md.

    raw: optional dict of the pre-parse source values, ONLY for
    bookmakers whose wire format needed an explicit conversion (e.g.
    BetKanyon's odds arrive as JSON strings/numbers cast via float()).
    Never pass anything containing session/auth data here.
    """

    if not TRACE_ENABLED:
        return

    key = _key(bookmaker, home_team, away_team, market, side)

    entry = {
        "stage": stage,
        "ts": time.time(),
        "home_odds": home_odds,
        "draw_odds": draw_odds,
        "away_odds": away_odds,
        "raw": raw,
    }

    _history[key].append(entry)

    raw_note = f" | raw={raw}" if raw else ""
    side_note = f"/{side}" if side else ""

    print(
        f"[ODDS-TRACE] stage={stage:<6} {bookmaker} | {home_team} vs {away_team} "
        f"({market}{side_note}) | home={home_odds} draw={draw_odds} "
        f"away={away_odds}{raw_note}"
    )


def record_engine_selection(event, best_odds):
    """
    Composite ENGINE-stage trace: which bookmaker was actually chosen
    for each of home/draw/away for one matched event, and the exact
    odds value carried forward into arbitrage calculation for each.
    """

    if not TRACE_ENABLED:
        return

    print(
        f"[ODDS-TRACE] stage=ENGINE {event.home_team} vs {event.away_team} "
        f"({event.market}) | "
        f"home={best_odds.home_odds}@{best_odds.home_match.bookmaker} "
        f"draw={best_odds.draw_odds}@{best_odds.draw_match.bookmaker} "
        f"away={best_odds.away_odds}@{best_odds.away_match.bookmaker}"
    )

    for leg_name, match in (
        ("home", best_odds.home_match),
        ("draw", best_odds.draw_match),
        ("away", best_odds.away_match),
    ):
        record(
            "ENGINE",
            match.bookmaker,
            event.home_team,
            event.away_team,
            event.market,
            match.side,
            match.home_odds,
            match.draw_odds,
            match.away_odds,
        )


def get_history(bookmaker, home_team, away_team, market, side=None):
    return list(_history.get(_key(bookmaker, home_team, away_team, market, side), []))


def compare_stages(bookmaker, home_team, away_team, market, side=None):
    """
    True  -- every recorded stage for this key carries IDENTICAL odds
              (proof nothing silently mutated the value anywhere).
    False -- at least one stage disagrees with the first.
    None  -- fewer than two recorded stages, nothing to compare yet.
    """

    history = get_history(bookmaker, home_team, away_team, market, side)

    if len(history) < 2:
        return None

    first = (history[0]["home_odds"], history[0]["draw_odds"], history[0]["away_odds"])

    return all(
        (h["home_odds"], h["draw_odds"], h["away_odds"]) == first
        for h in history
    )


def reset():
    """Test helper: clear all recorded history."""
    _history.clear()
