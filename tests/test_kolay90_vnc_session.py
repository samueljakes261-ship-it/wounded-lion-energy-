"""RealVNC session host for Kolay90. No desktop and no network."""

from __future__ import annotations

import json

from parsers.kolay90_prematch import vnc_session
from parsers.kolay90_prematch.worker import Kolay90PrematchWorker


def test_tigervnc_list_parser_reads_display_numbers():
    text = "\n".join(
        [
            "TigerVNC server sessions:",
            "",
            "X DISPLAY # RFB PORT # PROCESS ID SERVER",
            ":1 5901 4242 Xtigervnc",
            "2 5902 4243 Xtigervnc",
        ]
    )
    assert vnc_session.parse_vnc_list(text) == {1, 2}
    assert vnc_session.parse_vnc_list("no sessions") == set()


def test_chrome_stays_down_until_xfce_is_up(monkeypatch):
    spawned = []
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv))
    monkeypatch.setattr(vnc_session, "_wait_until", lambda predicate, seconds=8.0: False)
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": True,
            "vnc_port": 5901,
            "vnc_listening": True,
            "display_running": True,
            "xfce_available": False,
            "cdp_listening": False,
            "vnc_server": "/usr/bin/tigervncserver",
            "chrome_bin": "/usr/bin/google-chrome",
        },
    )
    result = vnc_session.ensure_desktop(autostart=True)
    assert result["ok"] is False
    assert result["failure"] == "xfce_desktop_down"
    assert spawned == []


def test_listed_desktop_is_not_started_again(monkeypatch, tmp_path):
    spawned = []
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv[0]))
    monkeypatch.setattr(vnc_session, "_wait_until", lambda predicate, seconds=8.0: True)
    monkeypatch.setattr(vnc_session, "chrome_profile_dir", lambda: tmp_path)
    monkeypatch.setattr(vnc_session, "chrome_using_profile", lambda profile=None: [])
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": True,
            "vnc_port": 5901,
            "vnc_listening": True,
            "vnc_listed": True,
            "display_running": True,
            "xfce_available": True,
            "cdp_listening": False,
            "vnc_server": "/usr/bin/tigervncserver",
            "chrome_bin": "/usr/bin/google-chrome",
        },
    )
    result = vnc_session.ensure_desktop(autostart=True)
    assert spawned == ["/usr/bin/google-chrome"]
    assert result["started"] == ["chrome"]


def test_display_and_vnc_port():
    assert vnc_session.display_number(":1") == 1
    assert vnc_session.vnc_tcp_port(":1") == 5901
    assert vnc_session.x_socket_path(":1").name == "X1"
    assert vnc_session.display_number("host:2") == 2


def test_commands_do_not_disable_auth_or_hide_chrome(monkeypatch):
    monkeypatch.delenv("KOLAY90_VNC_GEOMETRY", raising=False)
    monkeypatch.delenv("KOLAY90_VNC_DEPTH", raising=False)
    vnc = vnc_session.vnc_argv("/usr/bin/tigervncserver", ":1")
    chrome = vnc_session.chrome_argv("/usr/bin/google-chrome", display=":1")
    blob = " ".join(vnc + chrome).lower()
    assert "securitytypes" not in blob
    assert "password" not in blob
    assert "--headless" not in blob
    assert "-localhost" in vnc
    assert "yes" in vnc
    assert "-depth" in vnc
    assert "24" in vnc
    assert "1600x900" in vnc
    assert "--remote-debugging-address=127.0.0.1" in chrome
    assert "--remote-debugging-port=9222" in chrome
    assert chrome[-1] == "https://kolay90.com/"
    assert vnc[:3] == ["/usr/bin/tigervncserver", ":1", "-geometry"]


def test_status_reports_listening_ports(monkeypatch, tmp_path):
    socket_dir = tmp_path / "X11"
    socket_dir.mkdir()
    (socket_dir / "X1").touch()
    monkeypatch.setattr(vnc_session, "x_socket_path", lambda display=None: socket_dir / "X1")
    monkeypatch.setenv("KOLAY90_VNC_DISPLAY", ":1")
    monkeypatch.setenv("KOLAY90_CDP_URL", "http://127.0.0.1:9222")

    def ports(host, port, timeout=0.3):
        return port == 5901

    monkeypatch.setattr(vnc_session, "port_open", ports)
    monkeypatch.setattr(vnc_session, "find_vnc_server", lambda: None)
    monkeypatch.setattr(vnc_session, "listed_display_numbers", lambda: {1})
    monkeypatch.setattr(vnc_session, "xfce_on_display", lambda display=None: True)
    monkeypatch.setattr(vnc_session, "xfce_installed", lambda: True)
    monkeypatch.setattr(vnc_session, "find_chrome", lambda: "/usr/bin/google-chrome")
    status = vnc_session.desktop_status()
    assert status["x_socket"] is True
    assert status["vnc_listening"] is True
    assert status["display_running"] is True
    assert status["xfce_available"] is True
    assert status["desktop_ready"] is True
    assert status["vnc_implementation"] == "tigervnc"
    assert status["cdp_listening"] is False
    blob = json.dumps(status).lower()
    assert "password" not in blob
    assert "cookie" not in blob


def test_status_check_does_not_launch_chrome(monkeypatch):
    spawned = []
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
            "chrome_profile": "/tmp/profile",
            "vnc_server": "/usr/bin/tigervncserver",
            "chrome_bin": "/usr/bin/google-chrome",
            "display_running": True,
            "xfce_available": True,
        },
    )
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv))
    result = vnc_session.ensure_desktop(autostart=False)
    assert result["ok"] is False
    assert result["failure"] == "chrome_cdp_down"
    assert spawned == []


def test_existing_chrome_is_not_replaced(monkeypatch):
    spawned = []
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": True,
            "vnc_port": 5901,
            "vnc_listening": True,
            "cdp_url": "http://127.0.0.1:9222",
            "cdp_listening": True,
            "chrome_profile": "/tmp/profile",
            "vnc_server": "/usr/bin/tigervncserver",
            "chrome_bin": "/usr/bin/google-chrome",
            "display_running": True,
            "xfce_available": True,
        },
    )
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append(argv))
    result = vnc_session.ensure_desktop(autostart=True)
    assert result["ok"] is True
    assert result["chrome"] == "already_running"
    assert spawned == []


def test_autostart_opens_vnc_then_chrome_once(monkeypatch, tmp_path):
    calls = {"n": 0}
    spawned = []

    def status():
        calls["n"] += 1
        up = calls["n"] > 1
        chrome_up = calls["n"] > 3
        return {
            "display": ":1",
            "x_socket": up,
            "vnc_port": 5901,
            "vnc_listening": up,
            "vnc_listed": up,
            "display_running": up,
            "xfce_available": up,
            "cdp_url": "http://127.0.0.1:9222",
            "cdp_listening": chrome_up,
            "chrome_profile": str(tmp_path),
            "vnc_server": "/usr/bin/tigervncserver",
            "chrome_bin": "/usr/bin/google-chrome",
        }

    monkeypatch.setattr(vnc_session, "desktop_status", status)
    monkeypatch.setattr(vnc_session, "_wait_until", lambda predicate, seconds=8.0: True)
    monkeypatch.setattr(vnc_session, "_spawn", lambda argv, env: spawned.append((argv, env.get("DISPLAY"))))
    monkeypatch.setattr(vnc_session, "chrome_profile_dir", lambda: tmp_path)
    result = vnc_session.ensure_desktop(autostart=True)
    assert [item[0][0] for item in spawned] == [
        "/usr/bin/tigervncserver",
        "/usr/bin/google-chrome",
    ]
    assert spawned[1][1] == ":1"
    assert result["ok"] is True
    assert result["started"] == ["vnc", "chrome"]


def test_missing_vnc_server_is_reported(monkeypatch):
    monkeypatch.setattr(
        vnc_session,
        "desktop_status",
        lambda: {
            "display": ":1",
            "x_socket": False,
            "vnc_port": 5901,
            "vnc_listening": False,
            "cdp_url": "http://127.0.0.1:9222",
            "cdp_listening": False,
            "vnc_server": None,
            "chrome_bin": "/usr/bin/google-chrome",
        },
    )
    result = vnc_session.ensure_desktop(autostart=True)
    assert result["ok"] is False
    assert result["failure"] == "vncserver_missing"


def test_operator_message_names_the_tigervnc_desktop():
    text = vnc_session.operator_message(
        "login_page",
        {
            "display": ":1",
            "vnc_port": 5901,
            "vnc_listening": True,
            "xfce_available": True,
            "cdp_listening": False,
        },
    )
    assert "TigerVNC display :1" in text
    assert "xfce_available=true" in text
    assert "port 5901" in text
    assert "vnc_listening=true" in text
    assert "cdp_listening=false" in text
    assert "Do not start a second Chrome." in text


def test_worker_points_at_the_realvnc_desktop_when_login_is_required(monkeypatch, tmp_path):
    monkeypatch.setenv("KOLAY90_SESSION_STATUS", str(tmp_path / "session.json"))
    worker = Kolay90PrematchWorker(poll_interval=30, feed=object())
    result = {
        "ok": False,
        "authenticated": False,
        "auth_required": True,
        "auth_state": "KOLAY90_AUTHENTICATION_REQUIRED",
        "failure": "login_page",
        "matches": [],
        "total_events": 0,
        "one_x_two": 0,
        "session_desktop": {
            "display": ":1",
            "vnc_port": 5901,
            "vnc_listening": True,
            "cdp_listening": True,
        },
    }
    worker._publish(result, 4.0)
    status = worker.get_status()
    assert status["status"] == "authentication_required"
    assert status["session_desktop"]["vnc_port"] == 5901
