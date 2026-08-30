from datetime import datetime, timezone

from kenyan.parsers._common_1x2 import extract_1x2_from_event_groups
from kenyan.parsers.onexbet_parser import parse_events


def test_type_1_2_3_mapping_verified_against_real_live_payload(fixture_loader):
    """
    Directly verifies the task's suggested type 1/2/3 = home/draw/away
    mapping against REAL in-play data rather than trusting the
    reconnaissance notes blindly: Chelsea (home) leading Brighton
    (away) 4-2 must show a short-priced favourite on type 1 and a long
    price on type 3.
    """
    payload = fixture_loader("onexbet_live.json")

    chelsea_event = next(
        e for e in payload if e["opponent1"]["fullName"] == "Chelsea"
    )
    prices = extract_1x2_from_event_groups(chelsea_event["eventGroups"])

    assert prices[1] < 2.0  # home (Chelsea, winning 4-2) -- short-priced favourite
    assert prices[3] > 10.0  # away (Brighton, losing 4-2) -- big outsider
    assert prices[2] > prices[1]  # draw priced higher than the favourite


def test_parse_live_events_from_real_fixture(fixture_loader):
    payload = fixture_loader("onexbet_live.json")
    matches = parse_events(payload, status="LIVE")

    assert len(matches) == 4
    chelsea = next(m for m in matches if m.home_team == "Chelsea")
    assert chelsea.away_team == "Brighton & Hove Albion"
    assert chelsea.bookmaker == "1xBet"
    assert chelsea.status == "LIVE"
    assert chelsea.home_odds == chelsea.home_odds  # sanity: numeric
    assert chelsea.home_odds < chelsea.away_odds


def test_parse_prematch_events_from_real_fixture_uses_same_grouped_shape(fixture_loader):
    """
    Regression test for an earlier mistaken assumption that 1xBet's
    prematch endpoint used a different ("flat") payload shape --
    directly re-verified live: prematch uses the SAME `eventGroups`
    shape as live. This fixture also includes a placeholder "Home vs
    Away" outright entry that must be rejected.
    """
    payload = fixture_loader("onexbet_prematch.json")
    reference_now = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

    matches = parse_events(payload, status="PREMATCH", reference_now=reference_now)

    names = {(m.home_team, m.away_team) for m in matches}
    assert ("Manchester United", "Ipswich Town") in names
    assert ("Real Madrid", "Malaga") in names
    assert ("Home", "Away") not in names  # placeholder outright market rejected

    for match in matches:
        assert match.status == "PREMATCH"
        assert match.market == "1X2"


def test_parse_prematch_events_rejects_events_not_today(fixture_loader):
    payload = fixture_loader("onexbet_prematch.json")
    reference_far_future = datetime(2027, 6, 1, tzinfo=timezone.utc)

    matches = parse_events(payload, status="PREMATCH", reference_now=reference_far_future)
    assert matches == []


def test_blocked_odds_are_excluded():
    event = {
        "sport": {"id": 1, "name": "Football"},
        "opponent1": {"fullName": "Team A"},
        "opponent2": {"fullName": "Team B"},
        "liga": {"name": "Test League"},
        "id": 1,
        "startTs": 1788094800,
        "eventGroups": [
            {
                "groupId": 1,
                "events": [
                    [{"type": 1, "cf": 1.5}],
                    [{"type": 2, "cf": 3.5, "blocked": True}],
                    [{"type": 3, "cf": 4.5}],
                ],
            }
        ],
    }
    matches = parse_events([event], status="LIVE")
    assert matches == []  # draw is blocked -> incomplete 1X2 -> rejected


def test_incomplete_markets_are_rejected():
    event = {
        "sport": {"id": 1, "name": "Football"},
        "opponent1": {"fullName": "Team A"},
        "opponent2": {"fullName": "Team B"},
        "liga": {"name": "Test League"},
        "id": 1,
        "startTs": 1788094800,
        "eventGroups": [
            {
                "groupId": 1,
                "events": [
                    [{"type": 1, "cf": 1.5}],
                    [{"type": 2, "cf": 3.5}],
                    # away (type 3) missing entirely
                ],
            }
        ],
    }
    assert parse_events([event], status="LIVE") == []


def test_timestamps_are_normalized_to_utc_datetime():
    event = {
        "sport": {"id": 1, "name": "Football"},
        "opponent1": {"fullName": "Team A"},
        "opponent2": {"fullName": "Team B"},
        "liga": {"name": "Test League"},
        "id": 42,
        "startTs": 1788094800,
        "eventGroups": [
            {
                "groupId": 1,
                "events": [
                    [{"type": 1, "cf": 1.5}],
                    [{"type": 2, "cf": 3.5}],
                    [{"type": 3, "cf": 4.5}],
                ],
            }
        ],
    }
    matches = parse_events([event], status="LIVE")
    assert len(matches) == 1
    assert matches[0].start_time == datetime.fromtimestamp(1788094800, tz=timezone.utc)
    assert matches[0].event_id == "42"


def test_malformed_payload_handled_gracefully():
    assert parse_events(None, status="LIVE") == []
    assert parse_events({}, status="LIVE") == []
    assert parse_events("not a payload", status="LIVE") == []
    assert parse_events([{"unexpected": "shape"}], status="LIVE") == []
    assert parse_events(["not-a-dict-event"], status="LIVE") == []
