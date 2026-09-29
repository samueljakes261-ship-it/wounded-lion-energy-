from datetime import datetime, timedelta, timezone

from kenyan.config import BET22, BETIKA, ONEXBET, SPORTPESA
from kenyan.engine import KenyanArbitrageEngine
from kenyan.matcher import KenyanEventMatcher, KenyanMatchFinder
from kenyan.models import KenyanMatchOdds


NOW = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)


def _match(
    bookmaker,
    home,
    away,
    home_odds=2.4,
    draw_odds=3.3,
    away_odds=3.1,
    start=None,
    event_id="",
    cluster_id="",
    status="LIVE",
):
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="Premier League",
        sport="Football",
        market="1X2",
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=start or NOW,
        collected_at=datetime.now(timezone.utc),
        event_id=event_id,
        cluster_id=cluster_id,
        status=status,
    )


def test_same_event_different_naming_conventions_match():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Chelsea FC", "Brighton & Hove Albion")
    right = _match(ONEXBET, "Chelsea", "Brighton & Hove Albion")
    assert matcher.is_same_event(left, right)


def test_abbreviation_and_alias_match():
    matcher = KenyanEventMatcher()
    betika = _match(BETIKA, "Man Utd", "Ipswich")
    onexbet = _match(ONEXBET, "Manchester United", "Ipswich Town")
    assert matcher.is_same_event(betika, onexbet)


def test_casing_and_punctuation_match():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "LEEDS UNITED", "Brentford FC")
    right = _match(BETIKA, "Leeds", "Brentford")
    assert matcher.is_same_event(left, right)


def test_three_character_prefix_collision_does_not_match():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Barnsley", "Reading")
    right = _match(BETIKA, "Barcelona", "Real Madrid")
    assert matcher.is_same_event(left, right) is False


def test_manchester_united_does_not_match_manchester_city():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Manchester United", "Chelsea")
    right = _match(BETIKA, "Manchester City", "Chelsea")
    assert matcher.is_same_event(left, right) is False


def test_barcelona_b_does_not_match_barcelona():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Barcelona B", "Girona")
    right = _match(BETIKA, "Barcelona", "Girona")
    assert matcher.is_same_event(left, right) is False


def test_different_leagues_with_similar_names_do_not_match_on_prefix_alone():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Arsenal", "Chelsea")
    right = _match(BETIKA, "Arsenal de Sarandi", "Chelsea")
    assert matcher.is_same_event(left, right) is False


def test_start_time_mismatch_is_rejected():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Chelsea", "Brighton", start=NOW)
    right = _match(
        BETIKA,
        "Chelsea",
        "Brighton",
        start=NOW + timedelta(hours=5),
    )
    decision, reason, _level = matcher.evaluate(left, right)
    assert decision == "REJECT"
    assert reason == "START_TIME_MISMATCH"


def test_compatible_start_times_still_match():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Chelsea", "Brighton", start=NOW)
    right = _match(
        BETIKA,
        "Chelsea",
        "Brighton",
        start=NOW + timedelta(minutes=30),
    )
    assert matcher.is_same_event(left, right)


def test_live_does_not_match_prematch():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Chelsea", "Brighton", status="LIVE")
    right = _match(BETIKA, "Chelsea", "Brighton", status="PREMATCH")
    assert matcher.is_same_event(left, right) is False


def test_bookmaker_event_ids_do_not_force_unrelated_events_together():
    finder = KenyanMatchFinder()
    events = finder.find(
        [
            _match(SPORTPESA, "Arsenal", "Chelsea", event_id="100"),
            _match(BETIKA, "Liverpool", "Everton", event_id="100"),
        ]
    )
    multi = [event for event in events if len(event.matches) > 1]
    assert multi == []


def test_ambiguous_duplicate_1xbet_events_are_rejected():
    finder = KenyanMatchFinder()
    events = finder.find(
        [
            _match(SPORTPESA, "Chelsea", "Brighton", event_id="sp-1"),
            _match(ONEXBET, "Chelsea", "Brighton", event_id="1x-main", cluster_id="g1:c0"),
            _match(ONEXBET, "Chelsea", "Brighton", event_id="1x-half", cluster_id="g1:c1"),
        ]
    )
    for event in events:
        books = [match.bookmaker for match in event.matches]
        assert books.count(ONEXBET) <= 1
        if SPORTPESA in books:
            assert ONEXBET not in books


def test_swapped_home_away_is_rejected():
    matcher = KenyanEventMatcher()
    left = _match(SPORTPESA, "Chelsea", "Brighton")
    right = _match(BETIKA, "Brighton", "Chelsea")
    decision, reason, _level = matcher.evaluate(left, right)
    assert decision == "REJECT"
    assert reason == "HOME_AWAY_ORDER_MISMATCH"


def test_engine_still_finds_implementable_arb_for_same_event():
    matches = [
        _match(SPORTPESA, "Chelsea FC", "Brighton & Hove Albion", 2.40, 3.30, 3.10),
        _match(BETIKA, "Chelsea", "Brighton", 2.55, 3.20, 3.00),
        _match(ONEXBET, "Chelsea", "Brighton & Hove Albion", 2.30, 3.50, 3.20),
        _match(BET22, "Chelsea", "Brighton & Hove Albion", 2.50, 3.40, 3.15),
    ]
    opportunities = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000)
    assert len(opportunities) == 1
    assert opportunities[0].result.arbitrage_exists is True
