import time
from datetime import datetime, timedelta, timezone

from kenyan.config import BETIKA, ONEXBET
from kenyan.engine import KenyanArbitrageEngine
from kenyan.match_snapshot import match_identity, merge_match_records, visible_matches
from kenyan.models import KenyanMatchOdds


def _match(event_id, home, away, status="LIVE", odds=2.1):
    now = datetime.now(timezone.utc)
    return KenyanMatchOdds(
        bookmaker="SportPesa",
        competition="X",
        sport="Football",
        market="1X2",
        home_team=home,
        away_team=away,
        home_odds=odds,
        draw_odds=3.3,
        away_odds=3.4,
        start_time=now,
        collected_at=now,
        event_id=event_id,
        status=status,
    )


def test_partial_poll_keeps_unseen_event_until_retention():
    first = _match("1", "A", "B", odds=2.10)
    records = merge_match_records({}, [first], now=1000.0, retention_seconds=45)
    assert [m.event_id for m in visible_matches(records, now=1000.0, retention_seconds=45)] == ["1"]

    second = _match("2", "C", "D", odds=2.20)
    records = merge_match_records(records, [second], now=1005.0, retention_seconds=45)
    ids = {m.event_id for m in visible_matches(records, now=1005.0, retention_seconds=45)}
    assert ids == {"1", "2"}
    assert records[match_identity(first)].match.home_odds == 2.10

    records = merge_match_records(records, [second], now=1010.0, retention_seconds=45)
    ids = {m.event_id for m in visible_matches(records, now=1010.0, retention_seconds=45)}
    assert ids == {"1", "2"}

    records = merge_match_records(records, [second], now=1051.0, retention_seconds=45)
    ids = {m.event_id for m in visible_matches(records, now=1051.0, retention_seconds=45)}
    assert ids == {"2"}


def test_live_and_prematch_match_identities_differ():
    live = _match("1", "A", "B", status="LIVE")
    pre = _match("1", "A", "B", status="PREMATCH")
    assert match_identity(live) != match_identity(pre)


def test_odds_update_replaces_same_identity():
    first = _match("1", "A", "B", odds=2.10)
    records = merge_match_records({}, [first], now=1000.0, retention_seconds=45)
    updated = _match("1", "A", "B", odds=2.20)
    records = merge_match_records(records, [updated], now=1005.0, retention_seconds=45)
    visible = visible_matches(records, now=1005.0, retention_seconds=45)
    assert len(visible) == 1
    assert visible[0].home_odds == 2.20


def test_merge_restamps_collected_at_to_poll_end():
    parse_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    match = _match("1", "A", "B")
    match.collected_at = parse_time
    poll_end = time.time()
    records = merge_match_records({}, [match], now=poll_end, retention_seconds=180)
    stored = records[match_identity(match)].match
    age = abs((stored.collected_at.timestamp() - poll_end))
    assert age < 1.0


def test_prematch_football_still_arbs_after_long_extra_sport_walk():
    parse_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    poll_end = time.time()
    now = datetime.fromtimestamp(poll_end, tz=timezone.utc)
    matches = [
        KenyanMatchOdds(
            bookmaker=ONEXBET,
            competition="X",
            sport="Football",
            market="1X2",
            home_team="Alpha",
            away_team="Beta",
            home_odds=2.10,
            draw_odds=3.30,
            away_odds=3.40,
            start_time=now,
            collected_at=parse_time,
            status="PREMATCH",
        ),
        KenyanMatchOdds(
            bookmaker=BETIKA,
            competition="X",
            sport="Football",
            market="1X2",
            home_team="Alpha",
            away_team="Beta",
            home_odds=2.00,
            draw_odds=3.90,
            away_odds=4.00,
            start_time=now,
            collected_at=parse_time,
            status="PREMATCH",
        ),
    ]
    records = merge_match_records({}, matches, now=poll_end, retention_seconds=180)
    visible = visible_matches(records, now=poll_end, retention_seconds=180)
    opportunities = KenyanArbitrageEngine().compute_opportunities(
        visible, bankroll=1000, now=now
    )
    assert len(opportunities) == 1
    assert opportunities[0].result.arbitrage_exists is True
