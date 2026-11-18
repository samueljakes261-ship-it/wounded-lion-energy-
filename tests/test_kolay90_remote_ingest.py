"""Local Kolay90 snapshots enter the existing prematch pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from models.match import MatchOdds
from parsers.kolay90_prematch.snapshot import (
    IngestRejected,
    accept_remote_snapshot,
    load_fresh_matches,
    match_to_payload,
    prefer_remote_kolay90,
)
from parsers.kolay90_prematch.vnc_session import chrome_argv


NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _match(collected_at=None, bookmaker="kolay90"):
    stamp = collected_at or NOW
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Super Lig",
        sport="Football",
        market="1X2",
        home_team="Home",
        away_team="Away",
        home_odds=2.1,
        draw_odds=3.2,
        away_odds=3.4,
        start_time=NOW + timedelta(hours=2),
        collected_at=stamp,
        feed_type="prematch",
    )


@pytest.fixture
def snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / "kolay90_remote_snapshot.json"
    monkeypatch.setenv("KOLAY90_REMOTE_SNAPSHOT", str(path))
    monkeypatch.setenv("KOLAY90_INGEST_TOKEN", "local-test-token")
    return path


def test_accepts_fresh_kolay90_rows_and_drops_secrets(snapshot_file):
    row = match_to_payload(_match())
    row["cookie"] = "session-secret"
    body = {
        "auth_phase": "AUTHENTICATED",
        "password": "do-not-store",
        "matches": [row],
    }
    result = accept_remote_snapshot(body, "Bearer local-test-token", NOW)
    assert result["accepted"] is True
    stored = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert "password" not in stored
    assert "cookie" not in json.dumps(stored)
    assert stored["matches"][0]["bookmaker"] == "kolay90"
    assert stored["matches"][0]["feed_type"] == "prematch"
    assert oct(snapshot_file.stat().st_mode & 0o777) == "0o600"


def test_rejects_a_wrong_token(snapshot_file):
    body = {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(_match())]}
    with pytest.raises(IngestRejected) as caught:
        accept_remote_snapshot(body, "Bearer wrong", NOW)
    assert caught.value.status_code == 401
    assert not snapshot_file.exists()


def test_refuses_ingest_when_the_token_is_unset(snapshot_file, monkeypatch):
    monkeypatch.delenv("KOLAY90_INGEST_TOKEN", raising=False)
    with pytest.raises(IngestRejected) as caught:
        accept_remote_snapshot({"matches": []}, "", NOW)
    assert caught.value.status_code == 503


def test_does_not_replace_a_snapshot_with_stale_or_expired_data(snapshot_file):
    first = accept_remote_snapshot(
        {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(_match())]},
        "local-test-token",
        NOW,
    )
    assert first["accepted"] is True
    older = _match(NOW - timedelta(seconds=30))
    second = accept_remote_snapshot(
        {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(older)]},
        "local-test-token",
        NOW,
    )
    assert second == {"accepted": False, "reason": "not_newer"}
    expired = accept_remote_snapshot(
        {"auth_phase": "SESSION_EXPIRED", "matches": []},
        "local-test-token",
        NOW,
    )
    assert expired["accepted"] is False
    stored = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert stored["count"] == 1
    stale = _match(NOW - timedelta(seconds=901))
    with pytest.raises(IngestRejected) as caught:
        accept_remote_snapshot(
            {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(stale)]},
            "local-test-token",
            NOW,
        )
    assert caught.value.reason == "stale"


def test_rejects_other_bookmakers_and_live_rows(snapshot_file):
    live = match_to_payload(_match())
    live["feed_type"] = "live"
    with pytest.raises(IngestRejected) as caught:
        accept_remote_snapshot(
            {"auth_phase": "AUTHENTICATED", "matches": [live]},
            "local-test-token",
            NOW,
        )
    assert caught.value.status_code == 400
    other = match_to_payload(_match(bookmaker="betkanyon"))
    other["bookmaker"] = "betkanyon"
    with pytest.raises(IngestRejected):
        accept_remote_snapshot(
            {"auth_phase": "AUTHENTICATED", "matches": [other]},
            "local-test-token",
            NOW,
        )


def test_fresh_snapshot_replaces_only_kolay90_worker_rows(snapshot_file):
    accept_remote_snapshot(
        {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(_match())]},
        "local-test-token",
        NOW,
    )
    worker_row = _match()
    worker_row.home_team = "Worker Home"
    chosen = prefer_remote_kolay90([worker_row], NOW)
    assert [match.home_team for match in chosen] == ["Home"]
    assert load_fresh_matches(NOW + timedelta(seconds=901)) is None
    assert prefer_remote_kolay90([worker_row], NOW + timedelta(seconds=901)) == [worker_row]


def test_prematch_tick_reads_the_remote_snapshot_without_a_local_worker(
    snapshot_file, monkeypatch, tmp_path
):
    import collector

    accept_remote_snapshot(
        {"auth_phase": "AUTHENTICATED", "matches": [match_to_payload(_match())]},
        "local-test-token",
        NOW,
    )
    seen = {}

    def capture(matches, bankroll):
        seen["teams"] = [match.home_team for match in matches]
        seen["bankroll"] = bankroll
        return [], [], []

    monkeypatch.setattr(collector, "build_prematch_opportunities", capture)
    monkeypatch.setattr(collector, "find_prematch_back_lay", lambda matches, log=False: [])
    monkeypatch.setattr(
        collector,
        "_betfair_collector_snapshot",
        lambda now_dt, now: {"name": "Betfair", "status": "running"},
    )
    for name in (
        "_betkanyon_prematch_worker",
        "_orbit_prematch_worker",
        "_onwin_prematch_worker",
        "_kolay90_prematch_worker",
        "_prematch_last_matched",
        "_prematch_last_opportunities",
        "_prematch_last_back_lay",
        "_prematch_back_lay_sig",
        "_prematch_last_cache_n",
    ):
        monkeypatch.setattr(collector, name, getattr(collector, name))
    monkeypatch.setattr(collector, "_betkanyon_prematch_worker", None)
    monkeypatch.setattr(collector, "_orbit_prematch_worker", None)
    monkeypatch.setattr(collector, "_onwin_prematch_worker", None)
    monkeypatch.setattr(collector, "_kolay90_prematch_worker", None)
    cache = tmp_path / "prematch.json"
    monkeypatch.setattr(collector, "PREMATCH_CACHE_FILE", cache)
    collector._run_prematch_tick(100, NOW)
    assert seen["teams"] == ["Home"]
    assert seen["bankroll"] == 100

    status_file = tmp_path / "status.json"
    monkeypatch.setattr(collector, "STATUS_FILE", status_file)
    stopped = {"status": "stopped", "error": None}
    collector._write_status(stopped, stopped, stopped, None, None, None, 0, 0, NOW)
    status = json.loads(status_file.read_text(encoding="utf-8"))
    kolay = status["collectors"]["kolay90_prematch"]
    assert kolay["rawStatus"] == "running"
    assert kolay["collectorStatus"] == "RUNNING"
    assert status["collectors"]["betkanyon_prematch"]["rawStatus"] == "stopped"
    assert status["collectors"]["orbit"]["rawStatus"] == "stopped"
    assert status["collectors"]["betkanyon"]["rawStatus"] == "stopped"


def test_chrome_debug_address_stays_on_localhost():
    argv = chrome_argv(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert "--remote-debugging-address=127.0.0.1" in argv
    assert "https://kolay90.com/" in argv
    assert "--headless" not in argv
    assert not any("0.0.0.0" in part for part in argv)


def test_transmit_retries_and_does_not_treat_a_failure_as_success(monkeypatch):
    from parsers.kolay90_prematch import local_collector

    calls = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    def post(url, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        if len(calls) < 2:
            raise local_collector.requests.ConnectionError("down")
        return Response(200, {"accepted": True, "count": 1, "collected_at": "stamp"})

    monkeypatch.setenv("KOLAY90_INGEST_URL", "https://vps.example/kolay90/prematch")
    monkeypatch.setenv("KOLAY90_INGEST_TOKEN", "local-test-token")
    monkeypatch.setattr(local_collector.requests, "post", post)
    monkeypatch.setattr(local_collector.time, "sleep", lambda _seconds: None)
    assert local_collector.transmit([_match()]) is True
    assert len(calls) == 2
    body = calls[0][1]
    assert body["auth_phase"] == "AUTHENTICATED"
    assert "cookie" not in json.dumps(body)
    assert calls[0][2]["Authorization"] == "Bearer local-test-token"

    def reject(url, json, headers, timeout):
        return Response(503, {})

    monkeypatch.setattr(local_collector.requests, "post", reject)
    assert local_collector.transmit([_match()]) is False
