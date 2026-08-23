"""Offline OnWin prematch parser/worker tests. No network.

Does not modify parsers.onwin live internals.
"""

from datetime import datetime, timezone

from models.match import MatchOdds
from parsers.onwin.parser import FOOTBALL_SPORT_ID, OnWinParser
from parsers.onwin_prematch.feed import OnwinPrematchFeed, _is_full_sports_tree
from parsers.onwin_prematch.parser import parse_prematch
from parsers.onwin_prematch.worker import OnwinPrematchWorker

SPORT = FOOTBALL_SPORT_ID
NOW = datetime.now(timezone.utc)


def _event(status: str, home: str, away: str, complete=True) -> dict:
    outcomes = {
        "outcome::p1": {"coefficient": 2.1, "updatedAt": 1},
        "outcome::draw": {"coefficient": 3.2, "updatedAt": 1},
        "outcome::p2": {"coefficient": 3.4, "updatedAt": 1},
    }
    if not complete:
        outcomes.pop("outcome::draw")
    return {
        "diff": {
            "status": status,
            "startTime": 1787400000000,
            "participants": {
                "team1": {"name": home, "teamId": "h"},
                "team2": {"name": away, "teamId": "a"},
            },
        },
        "scopes": {
            "normal_time--0": {
                "markets": {
                    "score_1x2--nil": {"outcomes": outcomes}
                }
            }
        },
    }


PAYLOAD = {
    "sports": {
        SPORT: {
            "categories": {
                "c1": {
                    "diff": {"name": "England"},
                    "tournaments": {
                        "t1": {
                            "diff": {"name": "League"},
                            "events": {
                                "live-1": _event("in_progress", "LiveHome", "LiveAway"),
                                "pre-1": _event("not_started", "PreHome", "PreAway"),
                                "done-1": _event("finished", "DoneHome", "DoneAway"),
                                "thin-1": _event(
                                    "not_started", "ThinHome", "ThinAway", complete=False
                                ),
                            },
                        }
                    },
                }
            }
        }
    }
}


def test_live_onwin_parser_still_keeps_only_in_progress():
    matches = OnWinParser().parse(PAYLOAD)
    assert len(matches) == 1
    assert matches[0].home_team == "LiveHome"
    assert getattr(matches[0], "feed_type", "live") == "live"


def test_prematch_parser_keeps_non_live_complete_1x2():
    matches = parse_prematch(PAYLOAD)
    assert len(matches) == 1
    match = matches[0]
    assert match.home_team == "PreHome"
    assert match.away_team == "PreAway"
    assert match.home_odds == 2.1
    assert match.draw_odds == 3.2
    assert match.away_odds == 3.4
    assert match.feed_type == "prematch"
    assert match.bookmaker == "OnWin"
    assert match.market == "1X2"
    assert match.start_time == datetime.fromtimestamp(1787400000, tz=timezone.utc)


def test_full_sports_tree_rejects_thin_get_main_line():
    assert _is_full_sports_tree(PAYLOAD) is True
    assert _is_full_sports_tree({"result": {}}) is False
    assert _is_full_sports_tree({"sports": {}}) is False
    assert _is_full_sports_tree([{"sports": {SPORT: {"categories": {}}}}]) is True


def test_feed_keeps_last_good_when_cycle_has_no_tree():
    feed = OnwinPrematchFeed.__new__(OnwinPrematchFeed)
    previous = {"sports": {SPORT: {"categories": {}}}}
    feed.browser = None
    feed._page = object()
    feed._latest = previous
    feed._last_good = ["kept"]
    feed.last_stats = {}
    feed._ensure_page = lambda: None
    feed._goto = lambda: None
    feed._wait_for_tree = lambda timeout_s=180: False

    result = OnwinPrematchFeed.collect_once(feed)

    assert result == ["kept"]
    assert feed._latest is previous


def test_worker_does_not_overwrite_last_good_with_empty_cycle():
    worker = OnwinPrematchWorker()
    kept = MatchOdds(
        bookmaker="OnWin",
        competition="League",
        sport="football",
        market="1X2",
        home_team="PreHome",
        away_team="PreAway",
        home_odds=2.1,
        draw_odds=3.2,
        away_odds=3.4,
        start_time=NOW,
        collected_at=NOW,
        feed_type="prematch",
    )
    worker._feed = type("Feed", (), {"get_parsed_event_count": lambda self: 1})()
    worker._publish_success([kept], 10)
    worker._publish_success([], 10)
    published = worker.get_matches()
    assert len(published) == 1
    assert published[0].home_team == "PreHome"


def test_start_prematch_workers_continues_when_onwin_constructor_raises(monkeypatch):
    import collector

    started = {"bk": False, "orbit": False}

    monkeypatch.setattr(
        collector,
        "_get_betkanyon_prematch_worker",
        lambda: started.__setitem__("bk", True),
    )
    monkeypatch.setattr(
        collector,
        "_get_orbit_prematch_worker",
        lambda: started.__setitem__("orbit", True),
    )
    monkeypatch.setattr(
        collector,
        "_get_onwin_prematch_worker",
        lambda: (_ for _ in ()).throw(RuntimeError("onwin prematch failed")),
    )

    collector.start_prematch_workers()

    assert started["bk"] is True
    assert started["orbit"] is True


def test_browser_uses_env_ws_and_skips_credential_manager(monkeypatch):
    from parsers.onwin_prematch.browser import OnwinPrematchBrowser

    calls = {"cdp": 0}
    page_holder = object()

    class FakeContext:
        def new_page(self):
            return page_holder

    class FakeBrowser:
        def __init__(self):
            self.contexts = [FakeContext()]

        def close(self):
            return None

    class FakeChromium:
        def connect_over_cdp(self, url):
            calls["cdp"] += 1
            assert "apikey=TESTKEY" in url
            assert "session_ttl=" in url
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            return None

    class FakeSync:
        def start(self):
            return FakePlaywright()

    monkeypatch.setenv("ZENROWS_BROWSER_WS", "wss://browser.zenrows.com/?apikey=TESTKEY")
    monkeypatch.setattr(
        "parsers.onwin_prematch.browser.sync_playwright", lambda: FakeSync()
    )
    monkeypatch.setattr(
        "parsers.onwin_prematch.browser.load_dotenv", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "credentials.zenrows_provider.connect_with_failover",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("OnWin prematch must not use CredentialManager")
        ),
    )

    browser = OnwinPrematchBrowser()
    page = browser.page()
    assert calls["cdp"] == 1
    assert page is page_holder
    browser.close()
