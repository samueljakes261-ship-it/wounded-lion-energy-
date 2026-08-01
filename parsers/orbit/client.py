import asyncio
import json

import websockets

from config import ORBIT_WS_URL, ORBIT_COOKIES


class OrbitWebSocketClient:
    def __init__(self):
        self.ws = None

    async def connect(self):
        print("Connecting...")

        self.ws = await websockets.connect(
            ORBIT_WS_URL,
            additional_headers={
                "Origin": "https://www.orbitxch.com",
                "Cookie": ORBIT_COOKIES,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/150.0.0.0 Safari/537.36"
                ),
            },
        )

        print("Connected!")

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

        print("Sending subscription...")
        print(payload)

        await self.ws.send(payload)

        print("Waiting for live messages...")

    async def receive(self):
        while True:
            message = await self.ws.recv()

            # SockJS open frame
            if message == "o":
                continue

            # SockJS heartbeat
            if message == "h":
                continue

            # SockJS close frame
            if message.startswith("c"):
                print("Socket closed:", message)
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
                    print("Failed to decode frame:")
                    print(message)
                    print(e)
                    continue

            # Sometimes Orbit sends raw JSON directly
            try:
                return json.loads(message)
            except Exception:
                print("Unknown frame:")
                print(message)

    async def close(self):
        if self.ws:
            await self.ws.close()


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