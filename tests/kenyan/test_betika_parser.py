from datetime import datetime, timezone

from kenyan.parsers.betika_parser import parse_matches


def test_parse_live_matches_from_real_fixture(fixture_loader):
    payload = fixture_loader("betika_live.json")
    matches = parse_matches(payload, status="LIVE")

    assert len(matches) == 4
    sunderland = next(m for m in matches if m.home_team == "Sunderland")
    assert sunderland.away_team == "Fulham"
    assert sunderland.bookmaker == "Betika"
    assert sunderland.status == "LIVE"
    assert sunderland.market == "1X2"
    assert sunderland.home_odds == 1.18
    assert sunderland.draw_odds == 5.50
    assert sunderland.away_odds == 40.00


def test_parse_prematch_today_only(fixture_loader):
    payload = fixture_loader("betika_prematch.json")
    reference_now = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

    matches = parse_matches(payload, status="PREMATCH", reference_now=reference_now)

    assert len(matches) == 4
    man_utd = next(m for m in matches if m.home_team == "Man Utd")
    assert man_utd.away_team == "Ipswich"
    assert man_utd.status == "PREMATCH"
    assert man_utd.home_odds == 1.38
    assert man_utd.draw_odds == 5.60
    assert man_utd.away_odds == 7.60


def test_parse_prematch_rejects_events_not_today(fixture_loader):
    payload = fixture_loader("betika_prematch.json")
    reference_far_future = datetime(2027, 3, 1, tzinfo=timezone.utc)

    matches = parse_matches(payload, status="PREMATCH", reference_now=reference_far_future)
    assert matches == []


def test_parse_matches_ignores_non_football():
    payload = {
        "data": [
            {
                "sport_name": "Basketball",
                "home_team": "A",
                "away_team": "B",
                "start_time": "2026-08-30 12:00:00",
                "odds": [
                    {
                        "sub_type_id": 1,
                        "name": "1X2",
                        "odds": [
                            {"outcome_id": "1", "odd_value": "1.5"},
                            {"outcome_id": "2", "odd_value": "3.5"},
                            {"outcome_id": "3", "odd_value": "4.5"},
                        ],
                    }
                ],
            }
        ]
    }
    assert parse_matches(payload, status="LIVE") == []


def test_parse_matches_handles_malformed_payload_gracefully():
    # No "data" key at all, and not even a dict.
    assert parse_matches({}, status="LIVE") == []
    assert parse_matches(None, status="LIVE") == []
    assert parse_matches({"data": "not-a-list"}, status="LIVE") == []


def test_parse_matches_rejects_incomplete_1x2():
    payload = {
        "data": [
            {
                "sport_name": "Soccer",
                "home_team": "A",
                "away_team": "B",
                "start_time": "2026-08-30 12:00:00",
                "odds": [
                    {
                        "sub_type_id": 1,
                        "name": "1X2",
                        "odds": [
                            {"outcome_id": "1", "odd_value": "1.5"},
                            {"outcome_id": "2", "odd_value": "0"},  # invalid
                        ],
                    }
                ],
            }
        ]
    }
    assert parse_matches(payload, status="LIVE") == []
