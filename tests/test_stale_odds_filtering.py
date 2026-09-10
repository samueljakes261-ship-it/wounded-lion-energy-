"""
Issue 1 ("stale cached odds displayed as live") regression coverage
for the per-MATCH freshness guard in collector.py
(_filter_stale_matches), which sits ON TOP OF the existing per-FEED
freshness guard (_check_feed_freshness).

Rationale: a bookmaker's overall feed can look perfectly healthy
(frequent touches) while one specific match's own price hasn't
actually been reconfirmed in a long time (e.g. a quiet market on a
push-based feed, or a delta protocol that silently stops repeating an
unchanged runner -- see test_orbit_parser_partial_delta_merge.py for
the concrete bug this defends against at a second layer).
"""

from datetime import datetime, timedelta, timezone

import collector
from models.match import MatchOdds


NOW = datetime.now(timezone.utc)


def _match(collected_at, bookmaker="OnWin"):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=NOW,
        collected_at=collected_at,
    )


def test_fresh_match_is_not_excluded():
    fresh = _match(NOW - timedelta(seconds=2))

    kept, stale_count = collector._filter_stale_matches([fresh], NOW)

    assert kept == [fresh]
    assert stale_count == 0


def test_match_older_than_max_age_is_excluded():
    stale = _match(NOW - timedelta(seconds=collector.MAX_ODDS_AGE_SECONDS + 5))

    kept, stale_count = collector._filter_stale_matches([stale], NOW)

    assert kept == []
    assert stale_count == 1


def test_only_the_stale_match_is_excluded_not_the_whole_batch():
    fresh = _match(NOW - timedelta(seconds=1), bookmaker="Betkanyon")
    stale = _match(NOW - timedelta(seconds=collector.MAX_ODDS_AGE_SECONDS + 10), bookmaker="Orbit")

    kept, stale_count = collector._filter_stale_matches([fresh, stale], NOW)

    assert kept == [fresh]
    assert stale_count == 1


def test_naive_and_aware_timestamps_are_both_handled_safely():
    """collected_at could theoretically be naive (no tzinfo) --
    _match_age_seconds must not raise, treating it as UTC."""

    naive_fresh = _match(NOW - timedelta(seconds=1))
    naive_fresh.collected_at = naive_fresh.collected_at.replace(tzinfo=None)

    kept, stale_count = collector._filter_stale_matches([naive_fresh], NOW)

    assert kept == [naive_fresh]
    assert stale_count == 0


def test_match_age_seconds_returns_none_when_no_timestamp():
    class _NoTimestamp:
        collected_at = None

    assert collector._match_age_seconds(_NoTimestamp(), NOW) is None
