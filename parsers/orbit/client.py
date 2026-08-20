import asyncio
import json
import random
import string

import websockets

from config import ORBIT_COOKIES

# config.ORBIT_WS_URL hardcodes a specific SockJS server-id/session-id
# pair (".../multiple-market-prices/610/2a9f9a94-.../websocket") that
# was captured from a single past browser session. SockJS session ids
# are single-use/ephemeral -- reusing an old one after that original
# connection ended causes the server to silently drop the opening
# handshake (observed: connect() then TimeoutError, no error frame).
# A fresh, randomly-generated server-id/session-id pair on the SAME
# base path works immediately as long as ORBIT_COOKIES is still a
# valid authenticated session (verified live). So we only reuse the
# fixed base path from config and generate the volatile suffix here,
# every time connect() is called (including on reconnects).
ORBIT_WS_BASE = (
    "wss://www.orbitxch.com/customer/ws/multiple-market-prices"
)

# Returned by receive() for a SockJS heartbeat ("h"). Distinct from a
# market-price payload (those always carry "marketDefinition") so the
# feed can treat heartbeats as connection liveness without pretending
# they are odds updates.
ORBIT_HEARTBEAT = {"__orbit_internal__": "heartbeat"}


def _fresh_sockjs_path() -> str:
    server_id = str(random.randint(0, 999)).zfill(3)
    session_id = "".join(
        random.choices(string.ascii_letters + string.digits, k=8)
    )
    return f"{ORBIT_WS_BASE}/{server_id}/{session_id}/websocket"


def is_orbit_heartbeat(frame) -> bool:
    return isinstance(frame, dict) and frame.get("__orbit_internal__") == "heartbeat"


class OrbitWebSocketClient:
    def __init__(self):
        self.ws = None

    async def connect(self):
        url = _fresh_sockjs_path()

        print("[ORBIT] Connecting websocket...")

        self.ws = await websockets.connect(
            url,
            additional_headers={
                "Origin": "https://www.orbitxch.com",
                "Cookie": ORBIT_COOKIES,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/150.0.0.0 Safari/537.36"
                ),
            },
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
        )

        # SockJS opening frame ("o") confirms the transport is actually
        # live before we report success -- otherwise a caller could
        # start subscribing on a socket that never really opened.
        open_frame = await asyncio.wait_for(self.ws.recv(), timeout=10)

        if open_frame != "o":
            raise ConnectionError(
                f"Expected SockJS open frame 'o', got: {open_frame!r}"
            )

        print("[ORBIT] Websocket connected")

    async def subscribe(self, market_id: str, event_id: str):
        payload = json.dumps(
            [
                json.dumps(
                    [
                        {
                            "marketId": market_id,
                            "eventId": event_id,
                            "applicationType": "WEB",
                        }
                    ]
                )
            ]
        )

        await self.ws.send(payload)

    async def receive(self):
        while True:
            message = await self.ws.recv()

            # SockJS open frame
            if message == "o":
                continue

            # SockJS heartbeat -- connection is alive. Must surface
            # this to the feed: swallowing it here made
            # asyncio.wait_for(receive(), 30s) raise TimeoutError on
            # a perfectly healthy socket whenever prices were quiet,
            # which tore down and resubscribed every live market.
            if message == "h":
                return ORBIT_HEARTBEAT

            # SockJS close frame
            if message.startswith("c"):
                print(f"[ORBIT] Socket closed by server: {message}")
                return None

            # SockJS message frame
            if message.startswith("a"):
                try:
                    outer = json.loads(message[1:])

                    if not outer:
                        continue

                    inner = outer[0]

                    if isinstance(inner, str):
                        return json.loads(inner)

                    return inner

                except Exception as e:
                    print(
                        f"[ORBIT] Failed to decode frame "
                        f"({type(e).__name__}: {e})"
                    )
                    continue

            # Sometimes Orbit sends raw JSON directly
            try:
                return json.loads(message)
            except Exception:
                print("[ORBIT] Unknown websocket frame (ignored)")

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None


async def demo():
    client = OrbitWebSocketClient()

    await client.connect()

    await client.subscribe(
        "1.260338641",
        "35856607",
    )

    while True:
        msg = await client.receive()

        if msg:
            print(json.dumps(msg, indent=2))


if __name__ == "__main__":
    asyncio.run(demo())
