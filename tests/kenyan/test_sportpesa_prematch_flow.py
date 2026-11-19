"""SportPesa PREMATCH session, catalogue pagination, and markets parsing."""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from kenyan.http_utils import FetchResult, fetch_json
from kenyan.parsers.sportpesa_parser import (
    PREMATCH_MARKETS_QUERY,
    assemble_prematch_matches,
    build_prematch_markets_url,
    parse_content_range,
    parse_todays_games,
)
from kenyan.workers import sportpesa


def _game(event_id=16167883, *, odds=("5.00", "4.00", "1.80"), timestamp_ms=None):
    when = timestamp_ms
    if when is None:
        when = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "id": event_id,
        "sport": {"id": 1, "name": "Football"},
        "competition": {"id": 7, "name": "League"},
        "competitors": [
            {"id": 11, "name": "FC Masar"},
            {"id": 12, "name": "EL Terasanah"},
        ],
        "dateTimestamp": when,
        "markets": [
            {
                "id": 10,
                "name": "1X2",
                "selections": [
                    {"name": "FC Masar", "shortName": "1", "odds": odds[0], "specValue": 0},
                    {"name": "Draw", "shortName": "X", "odds": odds[1], "specValue": 0},
                    {"name": "EL Terasanah", "shortName": "2", "odds": odds[2], "specValue": 0},
                ],
            }
        ],
    }


def _ok(url, body, *, content_range=None, content_type="application/json"):
    return FetchResult(
        url=url,
        ok=True,
        status_code=206,
        content_type=content_type,
        response_size_bytes=32,
        elapsed_seconds=0.01,
        json_body=body,
        content_range=content_range,
    )


def _patch_session(monkeypatch):
    monkeypatch.setattr(sportpesa, "PREMATCH_REQUEST_PACE_SECONDS", 0)
    monkeypatch.setattr(sportpesa, "establish_prematch_session", lambda: (object(), None))


def test_navigation_cookie_is_reused_on_the_catalogue_request(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.cookies_set = {}

        def get(self, url, headers=None, timeout=None):
            assert "/api/" not in url
            self.cookies_set["visited"] = "synthetic-session"

            class Response:
                status_code = 200
                headers = {"content-type": "text/html; charset=utf-8"}
                content = b"<html>sportpesa</html>"
                text = "<html>sportpesa</html>"

            return Response()

        class cookies:
            pass

    holder = {}

    class Session(FakeSession):
        def __init__(self):
            super().__init__()
            holder["session"] = self
            self._jar = {"visited": None}

        def get(self, url, headers=None, timeout=None):
            self._jar["visited"] = "synthetic-session"
            return super().get(url, headers=headers, timeout=timeout)

    # requests cookie jars expose .get; the fake only needs that.
    class Jar:
        def __init__(self, owner):
            self.owner = owner

        def get(self, name):
            return self.owner._jar.get(name)

    def session_factory():
        session = Session()
        session.cookies = Jar(session)
        return session

    monkeypatch.setattr(sportpesa.requests, "Session", session_factory)
    monkeypatch.setattr(sportpesa, "PREMATCH_REQUEST_PACE_SECONDS", 0)

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        assert session is holder["session"]
        assert session.cookies.get("visited") == "synthetic-session"
        assert headers["X-App-Timezone"] == "Africa/Nairobi"
        assert headers["X-Requested-With"] == "XMLHttpRequest"
        assert headers["Accept"] == "application/json, text/plain, */*"
        assert headers["Referer"] == "https://www.sportpesa.com/"
        return _ok(url, [], content_range="0-0/0")

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert matches == []
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.catalogue_status == "empty_complete"


def test_json_body_is_accepted_when_content_type_is_html():
    class Response:
        status_code = 206
        headers = {
            "content-type": "text/html; charset=utf-8",
            "content-range": "0-0/1",
        }
        content = b'[{"id":16167883}]'
        text = '[{"id":16167883}]'

        def json(self):
            return [{"id": 16167883}]

    class Session:
        def get(self, url, headers=None, timeout=None):
            return Response()

    result = fetch_json("https://www.sportpesa.com/api/todays/1/games", session=Session())
    assert result.ok is True
    assert result.json_body == [{"id": 16167883}]
    assert result.content_range == "0-0/1"
    assert result.status_code == 206


def test_prematch_list_then_markets_uses_prematch_ids(monkeypatch, fixture_loader):
    markets = fixture_loader("sportpesa_prematch_markets.json")
    calls = []
    _patch_session(monkeypatch)

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        calls.append(url)
        if "/api/games/markets" in url:
            assert "16167883" in url
            assert "2369392" not in url
            assert PREMATCH_MARKETS_QUERY in url
            assert "194%230%230" not in url
            return _ok(url, markets, content_type="application/json")
        assert "/api/todays/1/games" in url
        assert "type=prematch" in url
        return _ok(url, [_game()], content_range="0-0/1", content_type="text/html; charset=utf-8")

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.snapshot_complete is True
    assert diagnostics.catalogue_status == "complete"
    assert diagnostics.terminal_reason == "content_range"
    assert diagnostics.source_total == 1
    assert diagnostics.unique_event_ids == 1
    winner = next(match for match in matches if match.market == "1X2")
    total = next(match for match in matches if match.market == "over_under")
    assert winner.home_odds == 1.50
    assert winner.draw_odds == 3.75
    assert winner.away_odds == 6.00
    assert winner.market_type == "MATCH_WINNER"
    assert winner.draw_odds is not None
    assert total.home_odds == 1.74
    assert total.away_odds == 2.02
    assert total.draw_odds is None
    assert total.line == 2.5
    assert total.market_type == "TOTAL"
    assert total.outcome_family == "total"
    assert total.period == "FULL_MATCH"
    assert total.source == "sportpesa_prematch"
    assert total.status == "PREMATCH"
    assert all("/api/live/" not in url for url in calls)


def test_live_markets_payload_is_not_parsed_as_prematch(fixture_loader):
    live = fixture_loader("sportpesa_live_markets.json")
    reference = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
    game = _game(timestamp_ms=int(reference.timestamp() * 1000), odds=("2.10", "3.20", "3.40"))
    matches = assemble_prematch_matches([game], live, reference_now=reference)
    assert matches
    assert all(match.market_id != "194" for match in matches)
    assert all(match.source == "sportpesa_prematch" for match in matches)
    assert all(match.status == "PREMATCH" for match in matches)
    winner = matches[0]
    assert winner.home_odds == 2.10
    assert parse_todays_games(live) == []


def test_http_200_html_is_a_source_failure(monkeypatch):
    _patch_session(monkeypatch)

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        return FetchResult(
            url=url,
            ok=False,
            status_code=200,
            content_type="text/html",
            response_size_bytes=120,
            elapsed_seconds=0.01,
            text_body="<html><title>Access Denied</title></html>",
            error="invalid JSON: Expecting value: line 1 column 1 (char 0)",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert matches == []
    assert diagnostics.endpoint_status == "http_error"
    assert diagnostics.catalogue_status == "failed"
    assert diagnostics.parser_error == "non-JSON HTML response"
    assert diagnostics.valid_normalized_events == 0


def test_challenge_page_is_a_source_failure(monkeypatch):
    _patch_session(monkeypatch)

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        return FetchResult(
            url=url,
            ok=False,
            status_code=200,
            content_type="text/html",
            response_size_bytes=200,
            elapsed_seconds=0.01,
            text_body="<title>Challenge Validation</title>",
            error="invalid JSON: Expecting value: line 1 column 1 (char 0)",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert matches == []
    assert diagnostics.catalogue_status == "failed"
    assert "anti-bot" in (diagnostics.parser_error or "")


def test_expired_session_mid_catalogue_keeps_earlier_page(monkeypatch):
    _patch_session(monkeypatch)
    calls = {"n": 0}

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ok(url, [_game()], content_range="0-0/2")
        return FetchResult(
            url=url,
            ok=False,
            status_code=200,
            content_type="text/html",
            response_size_bytes=80,
            elapsed_seconds=0.01,
            text_body="<html>Challenge Validation</html>",
            error="invalid JSON",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.snapshot_complete is False
    assert diagnostics.catalogue_status == "partial"
    assert diagnostics.terminal_reason == "non_json_html"
    assert len(matches) == 1
    assert matches[0].home_team == "FC Masar"


def test_http_error_malformed_json_and_missing_event_id(monkeypatch):
    _patch_session(monkeypatch)

    def http_error(url, headers=None, timeout=None, retries=0, session=None):
        return FetchResult(
            url=url,
            ok=False,
            status_code=503,
            content_type="text/plain",
            response_size_bytes=3,
            elapsed_seconds=0.01,
            error="HTTP 503",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", http_error)
    matches, diagnostics = sportpesa._poll_prematch()
    assert matches == []
    assert diagnostics.endpoint_status == "http_error"
    assert diagnostics.catalogue_status == "failed"

    def malformed(url, headers=None, timeout=None, retries=0, session=None):
        return FetchResult(
            url=url,
            ok=False,
            status_code=200,
            content_type="application/json",
            response_size_bytes=4,
            elapsed_seconds=0.01,
            text_body="not-json",
            error="invalid JSON: Expecting value: line 1 column 1 (char 0)",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", malformed)
    matches, diagnostics = sportpesa._poll_prematch()
    assert matches == []
    assert diagnostics.endpoint_status == "bad_payload"
    assert "invalid JSON" in (diagnostics.parser_error or "")

    urls = []

    def missing_id(url, headers=None, timeout=None, retries=0, session=None):
        urls.append(url)
        if "/api/games/markets" in url:
            assert "games=&" not in url
            assert "16167883" in url
            return _ok(url, {})
        return _ok(
            url,
            [_game(), {"sport": {"id": 1}, "competitors": [{"name": "A"}, {"name": "B"}]}],
            content_range="0-1/2",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", missing_id)
    reasons = []

    def capture_log(*_args, **kwargs):
        if kwargs.get("reason"):
            reasons.append(kwargs["reason"])

    monkeypatch.setattr("kenyan.parsers.sportpesa_parser.log_parse", capture_log)
    matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.unique_event_ids == 1
    assert "MISSING_EVENT_ID" in reasons
    assert any("/api/games/markets" in url for url in urls)
    assert matches


def test_content_range_pagination_marks_the_catalogue_complete(monkeypatch):
    _patch_session(monkeypatch)
    pages = {
        1: (0, 14, 30),
        16: (15, 29, 30),
    }

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        if "/api/games/markets" in url:
            return _ok(url, {})
        pag_min = int(parse_qs(urlsplit(url).query)["pag_min"][0])
        start, end, total = pages[pag_min]
        body = [
            {
                "id": start + index,
                "sport": {"id": 1},
                "competitors": [{"name": "A"}, {"name": "B"}],
                "dateTimestamp": 1_700_000_000_000,
                "markets": [],
            }
            for index in range(start, end + 1)
        ]
        return _ok(url, body, content_range=f"{start}-{end}/{total}")

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    _matches, diagnostics = sportpesa._poll_prematch()
    assert diagnostics.pages_fetched == 2
    assert diagnostics.source_total == 30
    assert diagnostics.unique_event_ids == 30
    assert diagnostics.duplicate_events == 0
    assert diagnostics.snapshot_complete is True
    assert diagnostics.terminal_reason == "content_range"
    assert diagnostics.catalogue_status == "complete"
    assert parse_content_range("0-14/69") == (0, 14, 69)
    assert "page=" not in build_prematch_markets_url([16167883])


def test_winner_and_total_lines_stay_distinct(fixture_loader):
    markets = fixture_loader("sportpesa_prematch_markets.json")
    second_line = {
        "id": 52,
        "name": "Total Goals Over/Under - Full Time",
        "specValue": 3.5,
        "selections": [
            {"name": "OVER 3.50", "shortName": "OV", "odds": "1.40", "specValue": 3.5},
            {"name": "UNDER 3.50", "shortName": "UN", "odds": "2.80", "specValue": 3.5},
        ],
    }
    repeated = dict(markets)
    repeated["16167883"] = list(markets["16167883"]) + [markets["16167883"][1], second_line]
    reference = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
    game = _game(timestamp_ms=int(reference.timestamp() * 1000))
    matches = assemble_prematch_matches([game, game], repeated, reference_now=reference)
    winners = [match for match in matches if match.market == "1X2"]
    totals = sorted(
        (match for match in matches if match.market == "over_under"),
        key=lambda match: match.line,
    )
    assert len(winners) == 1
    assert winners[0].home_odds == 1.50
    assert winners[0].draw_odds == 3.75
    assert winners[0].away_odds == 6.00
    assert [match.line for match in totals] == [2.5, 3.5]
    assert totals[0].draw_odds is None
    assert totals[1].home_odds == 1.40
    assert totals[1].away_odds == 2.80


def test_malformed_odds_are_rejected(monkeypatch):
    reference = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
    game = _game(timestamp_ms=int(reference.timestamp() * 1000))
    game["markets"] = []
    payload = {
        "16167883": [
            {
                "id": 10,
                "name": "1X2",
                "selections": [
                    {"shortName": "1", "name": "Home", "odds": "0.00"},
                    {"shortName": "X", "name": "Draw", "odds": "3.75"},
                    {"shortName": "2", "name": "Away", "odds": "6.00"},
                ],
            }
        ]
    }
    reasons = []

    def capture_log(*_args, **kwargs):
        if kwargs.get("reason"):
            reasons.append(kwargs["reason"])

    monkeypatch.setattr("kenyan.parsers.sportpesa_parser.log_parse", capture_log)
    matches = assemble_prematch_matches([game], payload, reference_now=reference)
    assert matches == []
    assert "MALFORMED_ODDS" in reasons


def test_failed_refresh_preserves_last_good_snapshot(monkeypatch):
    _patch_session(monkeypatch)
    state = {"mode": "ok"}

    def fake_fetch(url, headers=None, timeout=None, retries=0, session=None):
        if state["mode"] != "ok":
            return FetchResult(
                url=url,
                ok=False,
                status_code=200,
                content_type="text/html",
                response_size_bytes=40,
                elapsed_seconds=0.01,
                text_body="<html>Access Denied</html>",
                error="invalid JSON",
            )
        if "/api/games/markets" in url:
            return _ok(url, {})
        return _ok(url, [_game()], content_range="0-0/1")

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    worker = sportpesa.build_prematch_worker()
    worker._run_one_cycle()
    assert len(worker.get_matches()) == 1
    assert worker.get_matches()[0].home_team == "FC Masar"
    state["mode"] = "html"
    worker._run_one_cycle()
    assert len(worker.get_matches()) == 1
    assert worker.get_matches()[0].home_odds == 5.00
    assert worker._last_diagnostics.catalogue_status == "failed"


def test_live_poll_does_not_use_the_prematch_session(monkeypatch, fixture_loader):
    events = fixture_loader("sportpesa_live_events.json")
    markets = fixture_loader("sportpesa_live_markets.json")
    headers_seen = []

    def boom():
        raise AssertionError("LIVE must not open the prematch session")

    def fake_fetch(url, headers=None):
        headers_seen.append(headers or {})
        if "/live/sports/" in url:
            return FetchResult(
                url=url,
                ok=True,
                status_code=200,
                content_type="application/json",
                response_size_bytes=10,
                elapsed_seconds=0.01,
                json_body=events,
            )
        return FetchResult(
            url=url,
            ok=True,
            status_code=200,
            content_type="application/json",
            response_size_bytes=10,
            elapsed_seconds=0.01,
            json_body=markets,
        )

    monkeypatch.setattr(sportpesa, "establish_prematch_session", boom)
    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_live()
    assert diagnostics.endpoint_status == "ok"
    assert matches
    assert all(match.status == "LIVE" for match in matches)
    assert all("X-App-Timezone" not in headers for headers in headers_seen)
    assert headers_seen[0]["Referer"] == "https://www.sportpesa.com/"
