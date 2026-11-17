"""Kolay90 RealVNC auth phases. No browser and no bookmaker."""

from __future__ import annotations

import json

from parsers.kolay90_prematch.auth_phase import (
    AUTHENTICATED,
    AUTHENTICATING,
    AUTHENTICATION_FAILED,
    AWAITING_MANUAL_AUTH,
    BROWSER_STARTING,
    NOT_INITIALIZED,
    SESSION_EXPIRED,
    derive_auth_phase,
    read_session_record,
    update_session_record,
)
from parsers.kolay90_prematch.worker import Kolay90PrematchWorker
from parsers.kolay90_prematch import vnc_session


def test_initial_state_is_not_initialized():
    assert derive_auth_phase() == NOT_INITIALIZED


def test_browser_startup_is_not_authenticated():
    assert derive_auth_phase(browser_starting=True, browser_listening=True) == BROWSER_STARTING


def test_visible_challenge_waits_for_manual_auth():
    phase = derive_auth_phase(
        browser_listening=True,
        page_state="LOGIN",
        fetch_failure="login_page",
    )
    assert phase == AWAITING_MANUAL_AUTH


def test_homepage_alone_is_not_authenticated():
    phase = derive_auth_phase(
        browser_listening=True,
        page_state="KOLAY90_UNKNOWN",
    )
    assert phase == AWAITING_MANUAL_AUTH
    assert phase != AUTHENTICATED


def test_in_progress_fetch_on_the_app_is_authenticating():
    assert (
        derive_auth_phase(
            browser_listening=True,
            page_state="AUTHENTICATED_APP",
            fetch_in_progress=True,
        )
        == AUTHENTICATING
    )


def test_parsed_getmaclar_is_authenticated():
    assert (
        derive_auth_phase(
            browser_listening=True,
            page_state="AUTHENTICATED_APP",
            fetch_authenticated=True,
        )
        == AUTHENTICATED
    )


def test_expired_session_is_not_a_successful_feed():
    phase = derive_auth_phase(
        browser_listening=True,
        page_state="LOGIN",
        fetch_failure="login_expired",
        previously_authenticated=True,
    )
    assert phase == SESSION_EXPIRED
    assert phase != AUTHENTICATED


def test_startup_failure_is_not_success():
    phase = derive_auth_phase(fetch_failure="chrome_missing", browser_listening=False)
    assert phase == AUTHENTICATION_FAILED
    assert phase != AUTHENTICATED


def test_profile_is_reused_and_private(monkeypatch, tmp_path):
    monkeypatch.setattr(vnc_session, "chrome_profile_dir", lambda: tmp_path / "profile")
    first = vnc_session.prepare_profile()
    second = vnc_session.prepare_profile()
    assert first == second
    assert first.is_dir()
    assert (first.stat().st_mode & 0o777) == 0o700


def test_same_profile_does_not_launch_a_second_chrome(monkeypatch, tmp_path):
    spawned = []
    monkeypatch.setattr(vnc_session, "prepare_profile", lambda path=None: tmp_path)
    monkeypatch.setattr(vnc_session, "chrome_using_profile", lambda profile=None: [77])
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv))
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": True,
            "vnc_port": 5901,
            "vnc_listening": True,
            "cdp_url": "http://127.0.0.1:9222",
            "cdp_listening": False,
            "chrome_profile": str(tmp_path),
            "vnc_server": "/usr/bin/vncserver-virtual",
            "chrome_bin": "/usr/bin/google-chrome",
        },
    )
    result = vnc_session.ensure_desktop(autostart=True)
    assert spawned == []
    assert result["failure"] == "chrome_profile_busy"


def test_restart_replaces_only_the_profile_chrome(monkeypatch, tmp_path):
    pids = [4321]
    killed = []
    spawned = []

    monkeypatch.setattr(vnc_session, "chrome_profile_dir", lambda: tmp_path)
    monkeypatch.setattr(vnc_session, "prepare_profile", lambda path=None: tmp_path)
    monkeypatch.setattr(vnc_session, "chrome_using_profile", lambda profile=None: list(pids))

    def kill(pid, _sig):
        killed.append(pid)
        pids.clear()

    monkeypatch.setattr(vnc_session.os, "kill", kill)
    monkeypatch.setattr(vnc_session, "_wait_until", lambda predicate, seconds=8.0: True)
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv[0]))
    monkeypatch.setattr(vnc_session, "find_chrome", lambda: "/usr/bin/google-chrome")
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": True,
            "vnc_port": 5901,
            "vnc_listening": True,
            "cdp_listening": False,
            "chrome_bin": "/usr/bin/google-chrome",
            "chrome_profile": str(tmp_path),
        },
    )
    result = vnc_session.restart_browser()
    assert killed == [4321]
    assert spawned == ["/usr/bin/google-chrome"]
    assert result["started"] == ["chrome"]
    assert "vncserver" not in " ".join(spawned)


def test_worker_reuses_authenticated_rows_and_keeps_their_timestamps(monkeypatch, tmp_path):
    monkeypatch.setenv("KOLAY90_SESSION_STATUS", str(tmp_path / "session.json"))

    class Row:
        def __init__(self):
            self.collected_at = "2026-11-17T10:00:00+00:00"
            self.home_team = "Alpha"

    row = Row()
    worker = Kolay90PrematchWorker(poll_interval=30, feed=object())
    worker._publish(
        {
            "ok": True,
            "authenticated": True,
            "auth_state": "AUTHENTICATED_APP",
            "matches": [row],
            "total_events": 1,
            "one_x_two": 1,
            "session_desktop": {"cdp_listening": True, "chrome_profile": str(tmp_path)},
        },
        5.0,
    )
    fresh = worker.get_status()
    assert fresh["auth_phase"] == AUTHENTICATED
    assert fresh["authenticated"] is True
    assert fresh["matches"][0] is row
    confirmed = fresh["last_update_at"]
    authed_at = fresh["last_authenticated_at"]

    worker._publish(
        {
            "ok": False,
            "authenticated": False,
            "auth_required": True,
            "auth_state": "KOLAY90_AUTHENTICATION_REQUIRED",
            "failure": "login_expired",
            "matches": [Row()],
            "kept_last_good": True,
            "total_events": 0,
            "one_x_two": 1,
            "session_desktop": {"cdp_listening": True, "display": ":1", "vnc_port": 5901},
        },
        4.0,
    )
    expired = worker.get_status()
    assert expired["auth_phase"] == SESSION_EXPIRED
    assert expired["authenticated"] is False
    assert expired["status"] == "authentication_required"
    assert expired["manual_intervention_required"] is True
    assert expired["matches"][0] is row
    assert expired["matches"][0].collected_at == "2026-11-17T10:00:00+00:00"
    assert expired["last_update_at"] == confirmed
    assert expired["last_authenticated_at"] == authed_at
    assert expired["last_authenticated_request_at"] == authed_at


def test_failed_authentication_does_not_publish_odds(monkeypatch, tmp_path):
    monkeypatch.setenv("KOLAY90_SESSION_STATUS", str(tmp_path / "session.json"))
    worker = Kolay90PrematchWorker(poll_interval=30, feed=object())
    worker._publish(
        {
            "ok": False,
            "authenticated": False,
            "failure": "chrome_missing",
            "matches": [],
            "total_events": 0,
            "one_x_two": 0,
        },
        1.0,
    )
    status = worker.get_status()
    assert status["auth_phase"] == AUTHENTICATION_FAILED
    assert status["authenticated"] is False
    assert status["matches"] == []
    assert status["last_update_at"] is None
    assert status["last_authenticated_at"] is None


def test_session_record_drops_secrets(monkeypatch, tmp_path):
    path = tmp_path / "session.json"
    monkeypatch.setenv("KOLAY90_SESSION_STATUS", str(path))
    path.write_text(
        json.dumps(
            {
                "auth_phase": "AUTHENTICATED",
                "cookie": "session=super-secret",
                "authorization": "Bearer super-secret",
                "apikey": "super-secret",
            }
        ),
        encoding="utf-8",
    )
    loaded = read_session_record()
    blob = json.dumps(loaded)
    assert "super-secret" not in blob
    assert "cookie" not in blob
    assert "Bearer" not in blob

    saved = update_session_record(
        phase=SESSION_EXPIRED,
        error="login_expired",
        profile=str(tmp_path / "chrome_profile"),
        browser_process="running",
    )
    text = path.read_text(encoding="utf-8")
    assert saved["manual_intervention_required"] is True
    assert "super-secret" not in text
    assert "login_expired" in text
    assert "chrome_profile" in text
    assert (path.stat().st_mode & 0o777) == 0o600
