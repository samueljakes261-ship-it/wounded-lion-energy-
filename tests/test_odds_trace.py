"""
Tests for debug/odds_trace.py -- the RAW -> PARSED -> ENGINE -> API
comparison mechanism (Issue 1), and a regression guard proving it
never logs anything resembling a credential/secret (Issue 1 explicitly
requires this; the credential-management system's own dedicated tests
cover the credentials/ package itself).
"""

import re

import pytest

from debug import odds_trace


@pytest.fixture(autouse=True)
def _isolate_trace(monkeypatch):
    monkeypatch.setattr(odds_trace, "TRACE_ENABLED", True)
    odds_trace.reset()
    yield
    odds_trace.reset()


def test_disabled_trace_is_a_cheap_no_op(monkeypatch, capsys):
    monkeypatch.setattr(odds_trace, "TRACE_ENABLED", False)

    odds_trace.record("RAW", "OnWin", "A", "B", "1X2", None, 2.1, 3.3, 4.4)

    assert odds_trace.get_history("OnWin", "A", "B", "1X2") == []
    assert capsys.readouterr().out == ""


def test_record_stores_and_prints_a_structured_line(capsys):
    odds_trace.record("PARSED", "Betkanyon", "A", "B", "Match Odds", None, 2.15, 3.4, 2.9)

    history = odds_trace.get_history("Betkanyon", "A", "B", "Match Odds")
    assert len(history) == 1
    assert history[0]["home_odds"] == 2.15

    out = capsys.readouterr().out
    assert "[ODDS-TRACE]" in out
    assert "stage=PARSED" in out
    assert "Betkanyon" in out
    assert "home=2.15" in out


def test_compare_stages_true_when_all_stages_agree():
    for stage in ("RAW", "PARSED", "ENGINE", "API"):
        odds_trace.record(stage, "OnWin", "A", "B", "1X2", None, 2.1, 3.3, 4.4)

    assert odds_trace.compare_stages("OnWin", "A", "B", "1X2") is True


def test_compare_stages_false_when_a_stage_disagrees():
    odds_trace.record("PARSED", "OnWin", "A", "B", "1X2", None, 2.1, 3.3, 4.4)
    odds_trace.record("ENGINE", "OnWin", "A", "B", "1X2", None, 2.2, 3.3, 4.4)  # mutated!

    assert odds_trace.compare_stages("OnWin", "A", "B", "1X2") is False


def test_compare_stages_none_with_insufficient_history():
    odds_trace.record("PARSED", "OnWin", "A", "B", "1X2", None, 2.1, 3.3, 4.4)

    assert odds_trace.compare_stages("OnWin", "A", "B", "1X2") is None


def test_history_is_bounded_per_key():
    for i in range(odds_trace._MAX_HISTORY_PER_KEY + 10):
        odds_trace.record("API", "Orbit", "A", "B", "Match Odds", "BACK", i, i, i)

    history = odds_trace.get_history("Orbit", "A", "B", "Match Odds", "BACK")
    assert len(history) == odds_trace._MAX_HISTORY_PER_KEY


# ----------------------------------------------------------------------
# Requirement 15: no credentials/secrets appear in logs.
# ----------------------------------------------------------------------

SECRET_LOOKING_PATTERNS = re.compile(
    r"(api[_-]?key|apikey|secret|token|bearer|password|credential|zenrows_ws)",
    re.IGNORECASE,
)


def test_odds_trace_output_never_resembles_a_secret(capsys):
    odds_trace.record(
        "RAW", "Betkanyon", "Real Madrid", "Barcelona", "Match Odds", None,
        2.15, 3.4, 2.9, raw={"home": "2.15", "draw": "3.4", "away": "2.9"},
    )
    odds_trace.record(
        "PARSED", "Orbit", "Real Madrid", "Barcelona", "Match Odds", "BACK",
        2.15, 3.4, 2.9,
    )

    out = capsys.readouterr().out
    assert not SECRET_LOOKING_PATTERNS.search(out), (
        "odds_trace output must only ever contain odds/team/market/"
        "timestamp data, never anything resembling a credential"
    )


def test_engine_selection_trace_never_resembles_a_secret(capsys):
    from models.match import MatchOdds
    from models.best_odds import BestOdds
    from models.matched_event import MatchedEvent
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    def match(bookmaker):
        return MatchOdds(
            bookmaker=bookmaker, competition="X", sport="football", market="1X2",
            home_team="A", away_team="B",
            home_odds=2.0, draw_odds=3.0, away_odds=4.0,
            start_time=now, collected_at=now,
        )

    event = MatchedEvent(sport="football", competition="X", home_team="A", away_team="B", market="1X2")
    best = BestOdds(home_match=match("OnWin"), draw_match=match("Betkanyon"), away_match=match("Orbit"))

    odds_trace.record_engine_selection(event, best)

    out = capsys.readouterr().out
    assert not SECRET_LOOKING_PATTERNS.search(out)
