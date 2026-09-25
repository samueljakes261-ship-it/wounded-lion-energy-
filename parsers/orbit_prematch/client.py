"""Prematch SockJS client.

Live parsers.orbit.client is reused for subscribe/receive/heartbeat
framing. Prematch overrides connect() so the websockets library does
not send its own keepalive pings: SockJS already sends "h" frames, and
library pings time out whenever catalogue subscribe bursts occupy the
event loop (observed: 1011 keepalive ping timeout, then a full REST
rebuild).
"""

import asyncio
import random
import string

from parsers.orbit.client import ORBIT_WS_BASE, OrbitWebSocketClient, open_orbit_websocket


def _fresh_sockjs_path() -> str:
    server_id = str(random.randint(0, 999)).zfill(3)
    session_id = "".join(
        random.choices(string.ascii_letters + string.digits, k=8)
    )
    return f"{ORBIT_WS_BASE}/{server_id}/{session_id}/websocket"


class OrbitPrematchWebSocketClient(OrbitWebSocketClient):
    async def connect(self):
        url = _fresh_sockjs_path()
        print("[ORBIT] Connecting websocket...")
        self.ws = await open_orbit_websocket(
            url,
            ping_interval=None,
            ping_timeout=None,
        )
        open_frame = await asyncio.wait_for(self.ws.recv(), timeout=10)
        if open_frame != "o":
            raise ConnectionError(
                f"Expected SockJS open frame 'o', got: {open_frame!r}"
            )
        print("[ORBIT] Websocket connected")
