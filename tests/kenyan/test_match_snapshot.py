from kenyan.match_snapshot import match_identity, merge_match_records, visible_matches
from kenyan.models import KenyanMatchOdds
from datetime import datetime, timezone


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
