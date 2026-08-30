"""BetKanyon LIVE endpoint, parser, and last-good snapshot tests. No network."""

from __future__ import annotations

from datetime import datetime, timezone

from parsers.betkanyon.adapter import BetkanyonAdapter
from parsers.betkanyon.feed import BetkanyonFeed
from parsers.betkanyon.fetcher import API, LIVE_PAGE, BetkanyonFetcher
from parsers.betkanyon.parser import parse_json
from parsers.betkanyon.worker import BETKANYON_POLL_INTERVAL
from models.match import MatchOdds


def _payload(home="Alpha FC", away="Beta FC", h=2.10, d=3.40, a=3.10, event_id=1001):
    return {
        "N": "Football",
        "EGN": "Football",
        "CNT": [
            {
                "N": "Testland",
                "CL": [
                    {
                        "N": "Test League",
                        "EGN": "Test League",
                        "E": [
                            {
                                "Id": event_id,
                                "EHT": home,
                                "HT": home,
                                "EAT": away,
                                "AT": away,
                                "D": "2026-08-27T12:00:00Z",
                                "StakeTypes": [
                                    {
                                        "Id": 1,
                                        "N": "Maç Sonucu",
                                        "Stakes": [
                                            {"SN": "1", "F": h},
                                            {"SN": "X", "F": d},
                                            {"SN": "2", "F": a},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_live_api_uses_new_getliveevents_url():
    assert "sport.bksp3.com" in API
    assert "/live/getliveevents" in API
    assert "sportId=1" in API
    assert "langId=2" in API
    assert "partnerId=107" in API
    assert "countryCode=KE" in API
    assert "betkanyon1617.com" not in API
    assert "Tools/RequestHelper" in LIVE_PAGE
    assert "betkanyon1617.com" not in LIVE_PAGE
    source = open("parsers/betkanyon/fetcher.py", encoding="utf-8").read()
    assert "betkanyon1617.com/tr/sport/live" not in source
    assert "getliveevents" in source
    assert "Tools/RequestHelper" in source
    assert "sport.bksp3.com" in source


def test_live_poll_interval_is_about_five_seconds():
    assert BETKANYON_POLL_INTERVAL == 5


def test_live_parser_extracts_football_1x2():
    parsed = parse_json(_payload())
    assert len(parsed) == 1
    event = parsed[0]
    assert event["home"] == "Alpha FC"
    assert event["away"] == "Beta FC"
    assert event["home_odds"] == 2.10
    assert event["draw_odds"] == 3.40
    assert event["away_odds"] == 3.10
    match = BetkanyonAdapter.to_match_odds(event)
    assert match.bookmaker == "Betkanyon"
    assert match.home_odds == 2.10


def test_live_parser_accepts_w1_x_w2_selection_names():
    payload = _payload()
    stakes = payload["CNT"][0]["CL"][0]["E"][0]["StakeTypes"][0]["Stakes"]
    stakes[0]["SN"] = "W1"
    stakes[0]["N"] = "Win1"
    stakes[0]["SC"] = 1
    stakes[1]["SN"] = "X"
    stakes[1]["SC"] = 2
    stakes[2]["SN"] = "W2"
    stakes[2]["N"] = "Win2"
    stakes[2]["SC"] = 3
    parsed = parse_json(payload)
    assert len(parsed) == 1
    assert parsed[0]["home_odds"] == 2.10
    assert parsed[0]["draw_odds"] == 3.40
    assert parsed[0]["away_odds"] == 3.10


def test_live_parser_empty_payload():
    assert parse_json({}) == []
    assert parse_json({"CNT": []}) == []


def test_live_parser_malformed_missing_markets():
    payload = _payload()
    payload["CNT"][0]["CL"][0]["E"][0]["StakeTypes"] = []
    assert parse_json(payload) == []


def test_live_feed_keeps_last_good_on_empty_parse():
    previous = MatchOdds(
        bookmaker="Betkanyon",
        competition="Test League",
        sport="Football",
        market="Match Odds",
        home_team="Alpha FC",
        away_team="Beta FC",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )
    feed = BetkanyonFeed.__new__(BetkanyonFeed)

    class FakeFetcher:
        def fetch(self):
            return "encrypted"

        def close(self):
            pass

    class FakeDecryptor:
        def decrypt(self, _encrypted):
            return {"CNT": []}

    feed.fetcher = FakeFetcher()
    feed.decryptor = FakeDecryptor()
    feed._match_odds = [previous]
    feed._parsed_event_count = 1
    kept = feed.collect_once()
    assert kept == [previous]
    assert feed.get_match_odds()[0].home_team == "Alpha FC"


def test_live_feed_keeps_last_good_on_empty_payload():
    previous = MatchOdds(
        bookmaker="Betkanyon",
        competition="Test League",
        sport="Football",
        market="Match Odds",
        home_team="Alpha FC",
        away_team="Beta FC",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )
    feed = BetkanyonFeed.__new__(BetkanyonFeed)

    class FakeFetcher:
        def fetch(self):
            return None

        def close(self):
            pass

    feed.fetcher = FakeFetcher()
    feed.decryptor = object()
    feed._match_odds = [previous]
    feed._parsed_event_count = 1
    kept = feed.collect_once()
    assert kept == [previous]


def test_live_feed_keeps_last_good_on_malformed_decrypt():
    previous = MatchOdds(
        bookmaker="Betkanyon",
        competition="Test League",
        sport="Football",
        market="Match Odds",
        home_team="Alpha FC",
        away_team="Beta FC",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )
    feed = BetkanyonFeed.__new__(BetkanyonFeed)

    class FakeFetcher:
        def fetch(self):
            return "encrypted"

        def close(self):
            pass

    class FakeDecryptor:
        def decrypt(self, _encrypted):
            return "<html>Just a moment...</html>"

    feed.fetcher = FakeFetcher()
    feed.decryptor = FakeDecryptor()
    feed._match_odds = [previous]
    feed._parsed_event_count = 1
    kept = feed.collect_once()
    assert kept == [previous]


def test_live_feed_replaces_snapshot_on_valid_cycle():
    previous = MatchOdds(
        bookmaker="Betkanyon",
        competition="Test League",
        sport="Football",
        market="Match Odds",
        home_team="Old Home",
        away_team="Old Away",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )
    feed = BetkanyonFeed.__new__(BetkanyonFeed)

    class FakeFetcher:
        def fetch(self):
            return "encrypted"

        def close(self):
            pass

    class FakeDecryptor:
        def decrypt(self, _encrypted):
            return _payload(home="New Home", away="New Away")

    feed.fetcher = FakeFetcher()
    feed.decryptor = FakeDecryptor()
    feed._match_odds = [previous]
    feed._parsed_event_count = 1
    matches = feed.collect_once()
    assert len(matches) == 1
    assert matches[0].home_team == "New Home"
    assert matches[0].away_team == "New Away"


def test_live_cdp_does_not_launch_chrome(monkeypatch):
    from parsers.betkanyon_prematch import cdp

    launches = []

    def fake_connect(url=None):
        launches.append(url or "default")
        raise RuntimeError("no chrome")

    monkeypatch.setenv("BETKANYON_LIVE_FETCH", "cdp")
    monkeypatch.setattr(cdp, "connect_existing_chrome", fake_connect)
    fetcher = BetkanyonFetcher()
    try:
        fetcher._connect()
    except RuntimeError as exc:
        assert "no chrome" in str(exc)
    assert launches
    assert fetcher._use_cdp is True
