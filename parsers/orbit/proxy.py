"""Orbit-only SOCKS5 proxy adapter.

Reads ORBIT_SOCKS5_PROXY for parsers.orbit REST/WebSocket clients.
Does not set HTTP_PROXY / HTTPS_PROXY / ALL_PROXY. Never logs
credentials or the authenticated proxy URL.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

_VALID_SCHEMES = {"socks5", "socks5h"}
_logged_mode = False


class OrbitProxyConfigError(ValueError):
    """ORBIT_SOCKS5_PROXY is set but not a usable socks5 URL."""


def configured_proxy_url() -> str | None:
    raw = (os.environ.get("ORBIT_SOCKS5_PROXY") or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in _VALID_SCHEMES:
        raise OrbitProxyConfigError(
            "ORBIT_SOCKS5_PROXY must be socks5://HOST:PORT "
            "or socks5://USER:PASS@HOST:PORT"
        )
    if not parsed.hostname:
        raise OrbitProxyConfigError("ORBIT_SOCKS5_PROXY is missing a host")
    if parsed.port is None:
        raise OrbitProxyConfigError("ORBIT_SOCKS5_PROXY is missing a port")
    return raw


def redact_proxy_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "invalid"
    port = parsed.port if parsed.port is not None else ""
    if parsed.username or parsed.password:
        return f"{parsed.scheme}://***@{host}:{port}"
    return f"{parsed.scheme}://{host}:{port}"


def log_acquisition_mode() -> None:
    global _logged_mode
    if _logged_mode:
        return
    _logged_mode = True
    if configured_proxy_url() is None:
        print("[ORBIT] Orbit acquisition using direct connection")
        return
    print("[ORBIT] Orbit acquisition using SOCKS5 proxy")


def requests_proxies() -> dict[str, str] | None:
    url = configured_proxy_url()
    log_acquisition_mode()
    if url is None:
        return None
    return {"http": url, "https": url}


def reraise_proxy_connect_failure(exc: BaseException) -> None:
    """If *exc* is a SOCKS/proxy transport failure, log and re-raise clearly."""
    proxy_types: tuple[type[BaseException], ...] = ()
    try:
        from websockets.exceptions import ProxyError as WsProxyError
        proxy_types += (WsProxyError,)
    except ImportError:
        pass
    try:
        from python_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError
        proxy_types += (ProxyError, ProxyConnectionError, ProxyTimeoutError)
    except ImportError:
        pass
    missing_socks = isinstance(exc, ImportError) and "python-socks" in str(exc)
    if missing_socks or (proxy_types and isinstance(exc, proxy_types)):
        print("[ORBIT] Orbit SOCKS5 proxy connection failed")
        raise ConnectionError("Orbit SOCKS5 proxy connection failed") from exc
