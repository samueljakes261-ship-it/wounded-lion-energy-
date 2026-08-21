from datetime import datetime, timezone

from engine.matcher import EventMatcher
from models.match import MatchOdds
from parsers.betkanyon_prematch.parser import parse_prematch
from parsers.orbit_prematch.catalogue import split_event_name, _implied_ok
from parsers.orbit_prematch.rest import (
    _extract_markets,
    _fetch_tab,
    _is_match_odds,
    get_upcoming_markets,
)
from prematch.matcher import PrematchEventMatcher, PrematchMatchFinder
from prematch.mode import is_prematch_only
from prematch.pipeline import build_prematch_opportunities


NOW = datetime.now(timezone.utc)


def _odds(bookmaker, home, away, h, d, a, feed_type="prematch", side=None):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market="Match Odds",
        home_team=home,
        away_team=away,
        home_odds=h,
        draw_odds=d,
        away_odds=a,
        start_time=NOW,
        collected_at=NOW,
        side=side,
        feed_type=feed_type,
    )


def _bk_payload(home, away, h, d, a, market_id=1, name="Maç Sonucu"):
    return {
        "SId": 1,
        "SN": "Futbol",
        "TId": 4567,
        "TN": "Test League",
        "events": [
            {
                "Id": 11,
                "EHT": home,
                "HT": home,
                "EAT": away,
                "AT": away,
                "D": "2026-08-22T18:00:00Z",
                "ECN": "Test League",
                "StakeTypes": [
                    {
                        "Id": market_id,
                        "N": name,
                        "Stakes": [
                            {"SN": "1", "N": "1", "SC": 1, "F": h},
                            {"SN": "X", "N": "X", "SC": 2, "F": d},
                            {"SN": "2", "N": "2", "SC": 3, "F": a},
                        ],
                    }
                ],
            }
        ],
    }


def test_prematch_only_mode_reads_env(monkeypatch):
    monkeypatch.setenv("ENGINE_MODE", "prematch")
    assert is_prematch_only() is True
    monkeypatch.setenv("ENGINE_MODE", "live")
    assert is_prematch_only() is False


def test_home_draw_away_from_sn_and_f():
    parsed, stats = parse_prematch(_bk_payload("Cordoba", "Girona", 2.78, 3.60, 2.40))
    assert stats["complete_1x2"] == 1
    event = parsed[0]
    assert event["home"] == "Cordoba"
    assert event["away"] == "Girona"
    assert event["home_odds"] == 2.78
    assert event["draw_odds"] == 3.60
    assert event["away_odds"] == 2.40


def test_impossible_1x2_book_is_rejected():
    parsed, stats = parse_prematch(_bk_payload("Alpha FC", "Beta FC", 12.0, 6.6, 5.9))
    assert parsed == []
    assert stats["complete_1x2"] == 0


def test_non_match_result_market_is_ignored():
    parsed, _stats = parse_prematch(
        _bk_payload("Alpha FC", "Beta FC", 2.1, 3.4, 3.2, market_id=702, name="Toplam Gol")
    )
    assert parsed == []


def test_al_prefix_does_not_false_match_prematch_events():
    matcher = PrematchEventMatcher()
    kalba = _odds("Betkanyon", "Al Ittihad Kalba", "Al Wasl Dubai", 2.2, 3.3, 3.1)
    ain = _odds("Orbit", "Al Ain", "Al Jazira", 12.0, 6.6, 5.9, side="BACK")
    assert matcher.is_same_event(kalba, ain) is False
    live_matcher = EventMatcher()
    # Live prefix matcher is intentionally unchanged and may collide;
    # prematch must not use it.
    assert live_matcher.is_same_event(kalba, ain) in (True, False)


def test_prematch_same_teams_still_match():
    finder = PrematchMatchFinder()
    events = finder.find(
        [
            _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.3, 3.4),
            _odds("Orbit", "Alpha FC", "Beta FC", 2.1, 3.4, 3.5, side="BACK"),
        ]
    )
    assert len(events) == 1
    assert len(events[0].matches) == 2


def test_live_and_prematch_still_do_not_match():
    matcher = PrematchEventMatcher()
    live = _odds("Betkanyon", "Alpha FC", "Beta FC", 2.0, 3.0, 4.0, feed_type="live")
    prematch = _odds("Orbit", "Alpha FC", "Beta FC", 2.1, 3.1, 3.8, side="BACK")
    assert matcher.is_same_event(live, prematch) is False


def test_single_bookmaker_arbitrage_is_not_emitted():
    matches = [
        _odds("Orbit", "Alpha FC", "Beta FC", 12.0, 6.6, 5.9, side="BACK"),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.05, 1.18, 1.20, side="LAY"),
    ]
    _matched, opportunities = build_prematch_opportunities(matches, bankroll=1000)
    assert opportunities == []


def test_orbit_event_name_split():
    home, away = split_event_name("Cordoba vs Girona")
    assert home == "Cordoba"
    assert away == "Girona"


def test_orbit_implied_book_guard():
    assert _implied_ok(2.78, 3.60, 2.40) is True
    assert _implied_ok(12.0, 6.6, 5.9) is False
    # A real LAY book can sit under 1.0; the guard is BACK-only.
    assert _implied_ok(2.36, 3.85, 4.0) is False


def test_orbit_match_odds_name_filter():
    assert _is_match_odds({"marketName": "Match Odds"}) is True
    assert _is_match_odds({"marketName": "Over/Under 2.5"}) is False
    assert _is_match_odds({"marketName": ""}) is False


def test_orbit_pagination_stops_on_last_flag(monkeypatch):
    pages = []

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    def fake_post(url, json=None, headers=None, timeout=None):
        pages.append(url)
        if "page=0" in url:
            return FakeResponse(
                {
                    "marketCatalogueList": {
                        "content": [
                            {
                                "marketId": "1.1",
                                "marketName": "Match Odds",
                                "inPlay": False,
                                "event": {"id": "e1", "inPlay": False},
                                "runners": [{"selectionId": 1, "runnerName": "A"}],
                            }
                        ]
                        * 20,
                        "last": False,
                        "totalPages": 2,
                        "totalElements": 21,
                    }
                }
            )
        return FakeResponse(
            {
                "marketCatalogueList": {
                    "content": [
                        {
                            "marketId": "1.2",
                            "marketName": "Match Odds",
                            "inPlay": False,
                            "event": {"id": "e2", "inPlay": False},
                            "runners": [{"selectionId": 1, "runnerName": "B"}],
                        }
                    ],
                    "last": True,
                    "totalPages": 2,
                    "totalElements": 21,
                }
            }
        )

    monkeypatch.setattr("parsers.orbit_prematch.rest.requests.post", fake_post)
    kept, stats = _fetch_tab("TODAY")
    assert stats["pages"] == 2
    assert len(pages) == 2
    assert len(kept) == 21


def test_today_tomorrow_future_merge_by_market_id(monkeypatch):
    def market(mid, tab):
        return {
            "marketId": mid,
            "marketName": "Match Odds",
            "inPlay": False,
            "event": {"id": mid, "inPlay": False},
            "runners": [{"selectionId": 1, "runnerName": "A"}],
        }

    def fake_fetch(tab):
        if tab == "TODAY":
            return [market("1.1", tab), market("1.2", tab)], {
                "tab": tab, "pages": 1, "raw": 2, "kept": 2, "rejected": {},
            }
        if tab == "TOMORROW":
            return [market("1.2", tab), market("1.3", tab)], {
                "tab": tab, "pages": 1, "raw": 2, "kept": 2, "rejected": {},
            }
        return [market("1.4", tab)], {
            "tab": tab, "pages": 1, "raw": 1, "kept": 1, "rejected": {},
        }

    monkeypatch.setattr("parsers.orbit_prematch.rest._fetch_tab", fake_fetch)
    markets = get_upcoming_markets()
    ids = {row["marketId"] for row in markets}
    assert ids == {"1.1", "1.2", "1.3", "1.4"}
