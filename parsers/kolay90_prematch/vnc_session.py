"""RealVNC desktop that holds the Kolay90 Chrome session.

The prematch worker never logs in and never starts a second browser.
An operator connects with RealVNC Viewer, completes Cloudflare and the
Kolay90 login in the Chrome window on this virtual desktop, and leaves
that window open. The worker then attaches to 127.0.0.1:9222.

This module does not type credentials, read cookies, or disable VNC
authentication. The RealVNC password stays in the server's own config.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from parsers.kolay90_prematch.cdp import cdp_url

DEFAULT_DISPLAY = ":1"
DEFAULT_GEOMETRY = "1280x800"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = ROOT / "experiments" / "kolay90_direct" / "chrome_profile"
VNC_CANDIDATES = ("vncserver-virtual", "vncserver")
CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)


def display_name() -> str:
    raw = (os.environ.get("KOLAY90_VNC_DISPLAY") or DEFAULT_DISPLAY).strip()
    if raw.startswith(":"):
        return raw
    if ":" in raw:
        return ":" + raw.rsplit(":", 1)[-1]
    return DEFAULT_DISPLAY


def display_number(display: str | None = None) -> int:
    text = display or display_name()
    try:
        return int(text.rsplit(":", 1)[-1])
    except ValueError:
        return 1


def vnc_tcp_port(display: str | None = None) -> int:
    return 5900 + display_number(display)


def x_socket_path(display: str | None = None) -> Path:
    return Path(f"/tmp/.X11-unix/X{display_number(display)}")


def chrome_profile_dir() -> Path:
    raw = (os.environ.get("KOLAY90_CHROME_PROFILE") or "").strip()
    return Path(raw) if raw else DEFAULT_PROFILE


def cdp_port(url: str | None = None) -> int:
    parsed = urlsplit(url or cdp_url())
    if parsed.port:
        return parsed.port
    return 9222


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def find_vnc_server() -> str | None:
    override = (os.environ.get("KOLAY90_VNC_SERVER") or "").strip()
    if override:
        return override
    for name in VNC_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def find_chrome() -> str | None:
    override = (os.environ.get("KOLAY90_CHROME_BIN") or "").strip()
    if override:
        return override
    for name in CHROME_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def vnc_argv(binary: str, display: str | None = None) -> list[str]:
    """Start a virtual desktop. Authentication stays in RealVNC's config."""
    return [
        binary,
        display or display_name(),
        "-geometry",
        (os.environ.get("KOLAY90_VNC_GEOMETRY") or DEFAULT_GEOMETRY).strip(),
    ]


def chrome_argv(
    binary: str,
    *,
    display: str | None = None,
    profile: Path | None = None,
    port: int | None = None,
) -> list[str]:
    """Visible Chrome on the VNC desktop. Debugging stays on localhost."""
    del display  # Chrome reads DISPLAY from the environment, not an argv flag.
    return [
        binary,
        f"--user-data-dir={profile or chrome_profile_dir()}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port if port is not None else cdp_port()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "https://kolay90.com/",
    ]


def operator_message(failure: str | None, desktop: dict) -> str:
    return (
        f"failure={failure} "
        f"RealVNC display {desktop.get('display')} "
        f"port {desktop.get('vnc_port')} "
        f"vnc_listening={str(bool(desktop.get('vnc_listening'))).lower()} "
        f"cdp_listening={str(bool(desktop.get('cdp_listening'))).lower()}. "
        "Open RealVNC Viewer on that desktop and complete "
        "Cloudflare and Kolay90 login in its Chrome window. "
        "Leave the window open. Do not start a second Chrome."
    )


def desktop_status() -> dict:
    display = display_name()
    url = cdp_url()
    port = vnc_tcp_port(display)
    socket_path = x_socket_path(display)
    return {
        "display": display,
        "x_socket": socket_path.exists(),
        "vnc_port": port,
        "vnc_listening": port_open("127.0.0.1", port),
        "cdp_url": url,
        "cdp_listening": port_open("127.0.0.1", cdp_port(url)),
        "chrome_profile": str(chrome_profile_dir()),
        "vnc_server": find_vnc_server(),
        "chrome_bin": find_chrome(),
    }


def _wait_until(predicate, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return predicate()


def _spawn(argv: list[str], env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_desktop(*, autostart: bool = False) -> dict:
    """Make sure the RealVNC desktop and its Chrome window exist.

    A desktop that is already up is left alone. Chrome is started only
    when nothing is listening on the CDP port, so a logged-in window
    is not replaced.
    """
    status = desktop_status()
    started = []
    display = status["display"]
    if not status["x_socket"] and not status["vnc_listening"]:
        if not autostart:
            status["ok"] = False
            status["failure"] = "vnc_desktop_down"
            status["started"] = started
            return status
        binary = status["vnc_server"]
        if not binary:
            status["ok"] = False
            status["failure"] = "vncserver_missing"
            status["started"] = started
            return status
        _spawn(vnc_argv(binary, display), os.environ.copy())
        started.append("vnc")
        ready = _wait_until(
            lambda: x_socket_path(display).exists() or port_open("127.0.0.1", status["vnc_port"])
        )
        status = desktop_status()
        status["started"] = started
        if not ready and not status["x_socket"] and not status["vnc_listening"]:
            status["ok"] = False
            status["failure"] = "vnc_desktop_down"
            return status

    if status["cdp_listening"]:
        status["ok"] = True
        status["chrome"] = "already_running"
        status["started"] = started
        return status
    if not autostart:
        status["ok"] = False
        status["chrome"] = "not_listening"
        status["failure"] = "chrome_cdp_down"
        status["started"] = started
        return status

    binary = status["chrome_bin"]
    if not binary:
        status["ok"] = False
        status["failure"] = "chrome_missing"
        status["started"] = started
        return status
    profile = chrome_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DISPLAY"] = display
    _spawn(chrome_argv(binary, display=display, profile=profile), env)
    started.append("chrome")
    ready = _wait_until(lambda: port_open("127.0.0.1", cdp_port()))
    status = desktop_status()
    status["started"] = started
    status["ok"] = ready
    status["chrome"] = "started" if ready else "not_listening"
    if not ready:
        status["failure"] = "chrome_cdp_down"
    return status


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command == "start":
        payload = ensure_desktop(autostart=True)
    elif command == "status":
        payload = desktop_status()
        payload["ok"] = bool(payload["vnc_listening"] or payload["x_socket"])
    else:
        print("usage: python -m parsers.kolay90_prematch.vnc_session [status|start]")
        return 2
    print(json.dumps(payload, indent=2))
    if command == "start" and payload.get("ok"):
        print(
            "Connect with RealVNC Viewer to this machine, display "
            f"{payload['display']} (TCP {payload['vnc_port']}). "
            "Complete Cloudflare and log in to Kolay90 in the Chrome window. "
            "Leave that window open."
        )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
