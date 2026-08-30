from datetime import datetime, timezone

from kenyan.parsers.sportpesa_parser import (
    build_live_discovery_url,
    build_live_markets_url,
    build_todays_games_url,
    extract_live_football_events,
    parse_live_markets,
    parse_todays_games,
)


def test_build_live_discovery_url_is_parameterized():
    url = build_live_discovery_url(limit=15, offset=15)
    assert "limit=15" in url
    assert "offset=15" in url
    assert url.startswith("https://www.sportpesa.com/api/live/sports/1/events")


def test_live_markets_url_is_built_dynamically_never_hardcoded():
    """
    The task explicitly requires event ids to never be hardcoded --
    the markets URL must always be constructed from whatever ids were
    just discovered.
    """
    ids = [1111, 2222, 3333]
    url = build_live_markets_url(ids)
    assert "eventId=1111,2222,3333" in url
    assert "sportId=1" in url

    # A different discovery result must produce a different URL.
    other_url = build_live_markets_url([9999])
    assert other_url != url
    assert "eventId=9999" in other_url


def test_extract_live_football_events_from_real_fixture(fixture_loader):
    payload = fixture_loader("sportpesa_live_events.json")
    events = extract_live_football_events(payload)

    assert len(events) == 3
    first = events[0]
    assert first["event_id"] == 1702585
    assert first["home_team"] == "Chelsea FC"
    assert first["away_team"] == "Brighton & Hove Albion"
    assert first["competition"] == "Premier League"


def test_extract_live_football_events_rejects_non_football():
    payload = {
        "events": [
            {
                "id": 1,
                "sport": {"id": 2, "name": "Basketball"},
                "competitors": [{"name": "A"}, {"name": "B"}],
                "tournament": {"name": "NBA"},
            }
        ]
    }
    assert extract_live_football_events(payload) == []


def test_parse_live_markets_from_real_fixture(fixture_loader):
    discovery_payload = fixture_loader("sportpesa_live_events.json")
    markets_payload = fixture_loader("sportpesa_live_markets.json")

    discovered = extract_live_football_events(discovery_payload)
    matches = parse_live_markets(markets_payload, discovered)

    assert len(matches) >= 1

    chelsea_match = next(m for m in matches if m.home_team == "Chelsea FC")
    assert chelsea_match.away_team == "Brighton & Hove Albion"
    assert chelsea_match.bookmaker == "SportPesa"
    assert chelsea_match.status == "LIVE"
    assert chelsea_match.market == "1X2"
    assert chelsea_match.home_odds == 1.01
    assert chelsea_match.draw_odds == 12.50
    assert chelsea_match.away_odds == 100.00


def test_parse_live_markets_rejects_incomplete_1x2():
    discovered = [
        {
            "event_id": 1,
            "home_team": "Team A",
            "away_team": "Team B",
            "competition": "Test League",
            "kickoff_utc": "2026-08-30T13:00:00Z",
        }
    ]
    markets_payload = {
        "markets": [
            {
                "eventId": 1,
                "markets": [
                    {
                        "id": 194,
                        "name": "1x2",
                        "selections": [
                            {"name": "Team A", "odds": "1.50", "status": "Open"},
                            {"name": "draw", "odds": "3.20", "status": "Suspended"},
                            {"name": "Team B", "odds": "5.00", "status": "Open"},
                        ],
                    }
                ],
            }
        ]
    }

    matches = parse_live_markets(markets_payload, discovered)
    assert matches == []  # draw is Suspended -> reject the whole market


def test_build_todays_games_url_is_date_scoped():
    url = build_todays_games_url(page_min=2, page_count=50)
    assert "section=today" in url
    assert "type=prematch" in url
    assert "pag_min=2" in url
    assert "pag_count=50" in url


def test_parse_todays_games_from_real_fixture_today(fixture_loader):
    payload = fixture_loader("sportpesa_todays_games.json")
    reference_now = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

    matches = parse_todays_games(payload, reference_now=reference_now)

    assert len(matches) == 3
    telstar_match = next(m for m in matches if m.home_team == "SC Telstar")
    assert telstar_match.away_team == "Ajax"
    assert telstar_match.status == "PREMATCH"
    assert telstar_match.home_odds == 5.40
    assert telstar_match.draw_odds == 4.90
    assert telstar_match.away_odds == 1.51


def test_parse_todays_games_ignores_events_not_today(fixture_loader):
    payload = fixture_loader("sportpesa_todays_games.json")
    reference_far_future = datetime(2027, 1, 1, tzinfo=timezone.utc)

    matches = parse_todays_games(payload, reference_now=reference_far_future)
    assert matches == []


def test_parse_todays_games_ignores_non_football():
    payload = [
        {
            "id": 1,
            "sport": {"id": 5, "name": "Tennis"},
            "competitors": [{"name": "A"}, {"name": "B"}],
            "dateTimestamp": 1788101100000,
            "markets": [],
        }
    ]
    reference_now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    assert parse_todays_games(payload, reference_now=reference_now) == []
