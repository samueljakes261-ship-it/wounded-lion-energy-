from kenyan.http_utils import FetchResult
from kenyan.workers import sportpesa


def _ok(url, body):
    return FetchResult(
        url=url,
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=128,
        elapsed_seconds=0.01,
        json_body=body,
    )


def test_sportpesa_live_poll_parses_fixture_payloads(monkeypatch, fixture_loader):
    events = fixture_loader("sportpesa_live_events.json")
    markets = fixture_loader("sportpesa_live_markets.json")

    def fake_fetch(url, headers=None):
        if "/live/sports/" in url:
            return _ok(url, events)
        return _ok(url, markets)

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_live()
    assert diagnostics.endpoint_status == "ok"
    assert diagnostics.parser_error is None
    assert diagnostics.football_events >= 1
    assert diagnostics.valid_normalized_events == len(matches)
    assert matches
    chelsea = next(match for match in matches if match.home_team == "Chelsea FC")
    assert chelsea.bookmaker == "SportPesa"
    assert chelsea.home_odds == 1.01
    assert chelsea.draw_odds == 12.50
    assert chelsea.away_odds == 100.00


def test_sportpesa_challenge_page_is_a_failed_acquisition(monkeypatch):
    def fake_fetch(url, headers=None):
        return FetchResult(
            url=url,
            ok=False,
            status_code=200,
            content_type="text/html",
            response_size_bytes=1876,
            elapsed_seconds=0.02,
            text_body="<title>Challenge Validation</title>",
            error="invalid JSON: Expecting value: line 1 column 1 (char 0)",
        )

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_live()
    assert matches == []
    assert diagnostics.endpoint_status == "http_error"
    assert "anti-bot" in (diagnostics.parser_error or "")
