"""The Onwin Playwright experiment stays off the production path."""

import json
from pathlib import Path

from experiments.onwin_playwright.compare import compare_matches
from experiments.onwin_playwright.observe import OnwinObserver
from experiments.onwin_playwright.redact import count_payload, header_summary, safe_endpoint
from models.match import MatchOdds
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
FOOTBALL = "d6934640-cf1d-11e9-864b-0242ac13000a"


def _payload():
    return {
        "sports": {
            FOOTBALL: {
                "categories": {
                    "cat": {
                        "diff": {"name": "Country"},
                        "tournaments": {
                            "tour": {
                                "diff": {"name": "League"},
                                "events": {
                                    "evt-1": {
                                        "diff": {
                                            "status": "in_progress",
                                            "startTime": 1700000000000,
                                            "participants": {
                                                "team1": {"name": "Home FC", "teamId": "h"},
                                                "team2": {"name": "Away FC", "teamId": "a"},
                                            },
                                        },
                                        "scopes": {
                                            "normal_time--0": {
                                                "markets": {
                                                    "score_1x2--nil": {
                                                        "outcomes": {
                                                            "outcome::p1": {"coefficient": 2.1, "updatedAt": 1},
                                                            "outcome::draw": {"coefficient": 3.2, "updatedAt": 1},
                                                            "outcome::p2": {"coefficient": 3.4, "updatedAt": 1},
                                                        }
                                                    },
                                                    "other": {
                                                        "outcomes": {
                                                            "outcome::over": {"coefficient": 1.8, "updatedAt": 1}
                                                        }
                                                    },
                                                }
                                            }
                                        },
                                    }
                                },
                            }
                        },
                    }
                }
            }
        }
    }


def test_secret_headers_are_not_copied():
    summary = header_summary(
        {
            "x-token": "super-secret-token",
            "x-message-metadata": "meta-secret",
            "cookie": "session=secret",
            "origin": "https://onwin4511.com",
            "content-type": "application/json",
        }
    )
    text = json.dumps(summary)
    assert "super-secret-token" not in text
    assert "meta-secret" not in text
    assert "session=secret" not in text
    assert summary["x-token"]["present"] is True
    assert summary["x-message-metadata"]["length"] == len("meta-secret")
    assert summary["origin"] == "https://onwin4511.com"


def test_endpoint_drops_the_query_string():
    endpoint = safe_endpoint(
        "https://api-onwin-tr--prd--sb.538.lol/front/rpc/get_main_line.erisgaming?token=secret"
    )
    assert endpoint["host"] == "api-onwin-tr--prd--sb.538.lol"
    assert endpoint["path"].endswith("get_main_line.erisgaming")
    assert endpoint["has_query"] is True
    assert "secret" not in json.dumps(endpoint)


def test_observer_parses_main_line_and_tracks_token_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "experiments.onwin_playwright.observe.OUTPUT",
        tmp_path,
    )
    observer = OnwinObserver()
    first = observer.observe_request(
        "POST",
        "https://api-onwin-tr--prd--sb.538.lol/rpc/get_main_line.erisgaming?x=1",
        {"x-token": "token-a", "x-message-metadata": "meta-a", "origin": "https://onwin4511.com"},
        '{"method":"get_main_line.erisgaming"}',
    )
    assert first["post"]["keys"] == ["method"]
    assert "token-a" not in json.dumps(first)
    body = json.dumps(_payload()).encode()
    response = observer.observe_response(
        "https://api-onwin-tr--prd--sb.538.lol/rpc/get_main_line.erisgaming",
        200,
        "application/json",
        body,
    )
    assert response["parser_rows"] == 1
    assert response["counts"]["events"] == 1
    assert response["counts"]["markets"] == 2
    assert response["counts"]["odds"] == 4
    observer.observe_request(
        "POST",
        "https://api-onwin-tr--prd--sb.538.lol/rpc/get_main_line.erisgaming",
        {"x-token": "token-b", "x-message-metadata": "meta-a"},
        None,
    )
    assert observer.token_refreshed is True
    assert observer.metadata_refreshed is False
    assert observer.x_token_present is True
    assert observer.x_message_metadata_present is True
    observer.write_artifacts()
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["zenrows_used"] is False
    assert status["published_to_engine"] is False
    assert status["parser_rows"] == 1
    assert "token-a" not in json.dumps(status)
    assert "token-b" not in json.dumps(status)


def test_comparison_counts_shared_events_without_a_browser():
    stamp = datetime(2026, 11, 22, tzinfo=timezone.utc)

    def match(home, odds):
        return MatchOdds(
            bookmaker="OnWin",
            competition="League",
            sport="football",
            market="1X2",
            home_team=home,
            away_team="Away",
            home_odds=odds,
            draw_odds=3.0,
            away_odds=4.0,
            start_time=stamp,
            collected_at=stamp,
        )

    result = compare_matches(
        [match("Home", 2.0), match("Other", 1.5)],
        [match("Home", 2.2)],
    )
    assert result["shared_events"] == 1
    assert result["odds_mismatch"] == 1
    assert result["only_experiment"] == 1
    assert result["only_production"] == 0


def test_production_modules_do_not_import_the_experiment():
    collector = (ROOT / "collector.py").read_text(encoding="utf-8")
    browser = (ROOT / "parsers" / "onwin" / "browser.py").read_text(encoding="utf-8")
    feed = (ROOT / "parsers" / "onwin" / "feed.py").read_text(encoding="utf-8")
    experiment = (ROOT / "experiments" / "onwin_playwright" / "run.py").read_text(encoding="utf-8")
    session = (ROOT / "experiments" / "onwin_playwright" / "session.py").read_text(encoding="utf-8")
    assert "onwin_playwright" not in collector
    assert "onwin_playwright" not in browser
    assert "onwin_playwright" not in feed
    imports = "\n".join(
        line
        for line in (experiment + "\n" + session).splitlines()
        if line.startswith("import ") or line.startswith("from ")
    )
    assert "zenrows" not in imports.lower()
    assert "OnwinBrowser" not in imports
    counts = count_payload(_payload())
    assert counts["odds"] == 4
    observer = OnwinObserver()
    assert observer.note_host("onwin4505.com") is True
    assert observer.note_host("onwin4505.com") is False
    observer.note_page("https://onwin4505.com/sportsbook/live/main-line/soccer?token=secret")
    assert observer.page_url == "onwin4505.com/sportsbook/live/main-line/soccer"
    assert "secret" not in observer.page_url
    observer.note_title("Just a moment...")
    assert observer.auth_status == "cloudflare_check"
    observer.note_title("Onwin Bahis ve Casino Sitesi")
    assert observer.auth_status == "site_open"
    xhr = observer.observe_request(
        "POST",
        "https://odds.example/frontserver/command",
        {},
        None,
        "xhr",
    )
    assert xhr is not None
    assert observer.should_print("POST", xhr["endpoint"]) is True
    assert observer.should_print("POST", xhr["endpoint"]) is False
