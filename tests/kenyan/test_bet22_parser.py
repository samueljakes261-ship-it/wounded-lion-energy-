from datetime import datetime, timezone

from kenyan.parsers.bet22_parser import parse_events


def test_navigation_payload_is_never_treated_as_match_data(fixture_loader):
    """
    GetSportsShortZip is confirmed navigation/index data only (sport
    names + counts, no teams/odds) -- this module's parser must never
    be pointed at it, and even if it accidentally were, it must not
    crash or fabricate matches from it.
    """
    navigation_payload = fixture_loader("bet22_sportsshortzip.json")

    # Sanity: this really is navigation data, not match data.
    first_sport = navigation_payload["Value"][0]
    assert "N" in first_sport and first_sport["N"] == "Football"
    assert "O1" not in first_sport
    assert "E" not in first_sport

    # Feeding it to the real match parser produces nothing rather than
    # garbage/incorrect "matches".
    assert parse_events(navigation_payload, status="LIVE") == []
    assert parse_events(navigation_payload, status="PREMATCH") == []


def test_parse_live_1x2_from_real_fixture(fixture_loader):
    payload = fixture_loader("bet22_live1x2.json")
    matches = parse_events(payload, status="LIVE")

    assert len(matches) == 4
    chelsea = next(m for m in matches if m.home_team == "Chelsea")
    assert chelsea.away_team == "Brighton & Hove Albion"
    assert chelsea.bookmaker == "22Bet"
    assert chelsea.status == "LIVE"
    assert chelsea.market == "1X2"
    # Same underlying provider as 1xBet -- prices should agree closely
    # (both platforms quoting the same real match at the same moment).
    assert chelsea.home_odds < 2.0
    assert chelsea.away_odds > 10.0


def test_type_1_2_3_mapping_matches_1xbet_convention(fixture_loader):
    payload = fixture_loader("bet22_live1x2.json")
    matches = parse_events(payload, status="LIVE")
    chelsea = next(m for m in matches if m.home_team == "Chelsea")

    assert chelsea.home_odds == 1.025
    assert chelsea.draw_odds == 17.0
    assert chelsea.away_odds == 51.0


def test_parse_prematch_today_only(fixture_loader):
    payload = fixture_loader("bet22_prematch1x2.json")

    # These fixture events are genuinely scheduled for 2026-09-23 (a
    # real future AFCON qualifying date, not "today" relative to when
    # this fixture was captured) -- confirms today-only filtering
    # actually rejects real non-today fixtures, not just synthetic ones.
    reference_when_captured = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_events(payload, status="PREMATCH", reference_now=reference_when_captured) == []

    reference_matching_fixture_date = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
    matches = parse_events(
        payload, status="PREMATCH", reference_now=reference_matching_fixture_date
    )
    assert len(matches) == 5
    assert {(m.home_team, m.away_team) for m in matches} >= {("Kenya", "Eritrea")}


def test_placeholder_home_away_fixtures_are_rejected():
    event = {
        "SI": 1,
        "SN": "Football",
        "O1": "Home",
        "O2": "Away",
        "O1I": 142205,
        "O2I": 142207,
        "S": 1788102000,
        "L": "Some outright market",
        "homeAwayFlag": True,
        "E": [
            {"T": 1, "C": 1.2, "G": 1},
            {"T": 2, "C": 10.0, "G": 1},
            {"T": 3, "C": 7.2, "G": 1},
        ],
    }
    reference_now = datetime.fromtimestamp(1788102000, tz=timezone.utc)
    matches = parse_events({"Value": [event]}, status="PREMATCH", reference_now=reference_now)
    assert matches == []


def test_1x2_mapping_rejects_incomplete_market():
    event = {
        "SI": 1,
        "SN": "Football",
        "O1": "Team A",
        "O2": "Team B",
        "S": 1788102000,
        "L": "Test League",
        "E": [
            {"T": 1, "C": 1.5, "G": 1},
            {"T": 2, "C": 3.5, "G": 1},
            # away (T=3) missing
        ],
    }
    reference_now = datetime.fromtimestamp(1788102000, tz=timezone.utc)
    matches = parse_events({"Value": [event]}, status="PREMATCH", reference_now=reference_now)
    assert matches == []


def test_malformed_payload_handled_gracefully():
    assert parse_events(None, status="LIVE") == []
    assert parse_events({}, status="LIVE") == []
    assert parse_events("garbage", status="LIVE") == []
    assert parse_events({"Value": "not-a-list"}, status="LIVE") == []
    assert parse_events({"Value": [123, "x", None]}, status="LIVE") == []
