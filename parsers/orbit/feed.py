import asyncio
import time

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.client import OrbitWebSocketClient, is_orbit_heartbeat
from parsers.orbit.parser import OrbitParser
from parsers.orbit.rest import get_all_live_markets


# How often to re-fetch the REST market catalogue while a WebSocket
# session is already open, so newly-started live events are picked up
# without requiring a full reconnect. Runs as a background task so it
# cannot stall websocket reads (the previous in-band refresh used
# blocking requests.post on the asyncio loop, which both delayed
# frames and was itself a common TimeoutError trigger).
CATALOGUE_REFRESH_SECONDS = 60

# How long the socket may go with ZERO frames -- including SockJS
# heartbeats -- before the connection is treated as dead. SockJS
# typically heartbeats well under this; a 30s wait that ignored
# heartbeats was the production reconnect storm.
SOCKET_SILENCE_SECONDS = 60


class OrbitFeed:
    """
    One Orbit Exchange acquisition session: REST catalogue + one
    persistent SockJS/WebSocket connection subscribed to every live
    market, kept open across many incoming price-update frames.

    Mirrors the role parsers/betkanyon/feed.py plays for
    BetkanyonWorker: this class does the work of ONE session and
    raises on failure; parsers/orbit/worker.py owns retrying/backoff,
    exactly like BetkanyonWorker does for BetkanyonFeed.
    """

    def __init__(self):
        self.client = OrbitWebSocketClient()
        self._catalogue = {}
        # market_id -> list[MatchOdds] (BACK and/or LAY), most recent
        # parsed snapshot for that single market only.
        self._matches_by_market = {}
        self._subscribed_ids = set()
        self._last_catalogue_refresh = 0.0
        self._catalogue_task = None
        # selection_id -> last known {"back", "lay", "traded_volume"},
        # shared across every receive_next() call for the lifetime of
        # this session. Orbit only repeats a runner's ladder in a frame
        # when that runner's own price just changed (see
        # parsers/orbit/parser.py), so this cache is what lets an
        # unrelated runner's frame resolve THIS runner to its real
        # last-known price instead of "unquoted".
        self._runner_ladders = {}
        # "odds" | "heartbeat" | "ignored" -- set by the most recent
        # receive_next() so the worker can bump odds-freshness only
        # when real prices arrived, not on SockJS heartbeats.
        self.last_frame_kind = "ignored"
        self._last_activity_at = None
        self._closed = False

    # ------------------------------------------------------------------
    # One-shot legacy flow (unchanged, used by existing reconnaissance
    # scripts such as parsers/orbit/test_feed.py).
    # ------------------------------------------------------------------

    async def collect_once(self):
        client = OrbitWebSocketClient()

        markets = get_all_live_markets()

        catalogue = {}

        for market in markets:
            catalogue[market["marketId"]] = market

        await client.connect()

        for market in markets:
            await client.subscribe(
                market["marketId"],
                market["event"]["id"],
            )

        collected = {}

        expected = len(markets)

        received = 0

        while received < expected:

            raw = await client.receive()

            if raw is None:
                continue

            if is_orbit_heartbeat(raw):
                continue

            if (
                "marketDefinition" not in raw
                or "id" not in raw
            ):
                continue

            market_id = raw["id"]

            if market_id not in catalogue:
                continue

            parsed = OrbitParser.parse(
                raw,
                catalogue[market_id],
            )

            matches = OrbitAdapter.to_match_odds_both_sides(parsed)

            if matches:
                collected[market_id] = matches

            received += 1

        await client.close()

        flat = [m for matches in collected.values() for m in matches]

        return flat

    def get_match_odds(self):
        return [
            match
            for matches in self._matches_by_market.values()
            for match in matches
        ]

    def seconds_since_activity(self):
        if self._last_activity_at is None:
            return None
        return time.monotonic() - self._last_activity_at

    # ------------------------------------------------------------------
    # Persistent mode: connect + subscribe ONCE, then keep receiving
    # frames on the same socket for as long as the session lives.
    # ------------------------------------------------------------------

    async def connect_and_subscribe(self):
        print("[ORBIT] Fetching live market catalogue...")
        markets = await asyncio.to_thread(get_all_live_markets)

        for market in markets:
            self._catalogue[market["marketId"]] = market

        self._last_catalogue_refresh = time.monotonic()

        await self.client.connect()
        print("[ORBIT] Page ready")

        print(f"[ORBIT] Subscribing to {len(markets)} live markets...")
        for market in markets:
            await self.client.subscribe(
                market["marketId"],
                market["event"]["id"],
            )
            self._subscribed_ids.add(market["marketId"])

        self._closed = False
        if self._catalogue_task is None or self._catalogue_task.done():
            self._catalogue_task = asyncio.create_task(
                self._catalogue_refresh_loop(),
                name="orbit-catalogue-refresh",
            )

        return len(markets)

    async def _catalogue_refresh_loop(self):
        """
        Periodically discover new live markets on the EXISTING
        websocket. Failures here must not tear down the price feed.

        The first refresh is delayed by a full interval so it cannot
        overlap the initial subscribe burst (live soak: a REST refresh
        at t+60s reset the remote connection and the websocket died
        immediately afterward).
        """
        try:
            await asyncio.sleep(CATALOGUE_REFRESH_SECONDS)
        except asyncio.CancelledError:
            raise

        while not self._closed:
            try:
                added = await self._refresh_catalogue()
                if added:
                    print(
                        f"[ORBIT] Catalogue refresh: subscribed to "
                        f"{added} new market(s) "
                        f"(total {len(self._subscribed_ids)})"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(
                    f"[ORBIT] WARNING: Catalogue refresh failed "
                    f"({type(exc).__name__}: {exc}); live session continues"
                )

            try:
                await asyncio.sleep(CATALOGUE_REFRESH_SECONDS)
            except asyncio.CancelledError:
                raise

    async def _refresh_catalogue(self):
        markets = await asyncio.to_thread(get_all_live_markets)
        self._last_catalogue_refresh = time.monotonic()
        new_count = 0

        for market in markets:
            market_id = market["marketId"]
            self._catalogue[market_id] = market

            if market_id in self._subscribed_ids:
                continue

            await self.client.subscribe(
                market_id,
                market["event"]["id"],
            )
            self._subscribed_ids.add(market_id)
            new_count += 1

        return new_count

    async def _maybe_refresh_catalogue(self):
        """
        Kept for tests that call receive_next() without
        connect_and_subscribe(). The live worker uses the background
        loop instead so REST cannot stall websocket reads.
        """
        if (
            time.monotonic() - self._last_catalogue_refresh
            < CATALOGUE_REFRESH_SECONDS
        ):
            return 0

        return await self._refresh_catalogue()

    async def receive_next(self):
        """
        Wait for and process exactly one incoming websocket frame.

        Returns the list of MatchOdds (BACK and/or LAY, whichever are
        fully quoted) produced from that single frame, or an empty
        list if the frame wasn't a usable market-price update (SockJS
        heartbeat, or a market outside our catalogue).

        Sets last_frame_kind so the worker can tell heartbeats apart
        from odds. Raises only when the socket is actually gone or
        silent of ALL frames (including heartbeats).
        """

        raw = await asyncio.wait_for(
            self.client.receive(),
            timeout=SOCKET_SILENCE_SECONDS,
        )

        self._last_activity_at = time.monotonic()

        if raw is None:
            self.last_frame_kind = "ignored"
            raise ConnectionError("Orbit websocket closed by server.")

        if is_orbit_heartbeat(raw):
            self.last_frame_kind = "heartbeat"
            return []

        if not isinstance(raw, dict) or "id" not in raw:
            self.last_frame_kind = "ignored"
            return []

        market_id = raw["id"]

        if market_id not in self._catalogue:
            self.last_frame_kind = "ignored"
            return []

        try:
            parsed = OrbitParser.parse(
                raw,
                self._catalogue[market_id],
                runner_cache=self._runner_ladders,
            )

            matches = OrbitAdapter.to_match_odds_both_sides(parsed)

        except (KeyError, ValueError, TypeError) as exc:
            # A single market's catalogue entry can be malformed or
            # incomplete without the persistent websocket session
            # itself being unhealthy. Skipping just this frame is a
            # parser failure, not a connection failure.
            print(
                f"[ORBIT] Skipping market {market_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            self.last_frame_kind = "ignored"
            return []

        if matches:
            self._matches_by_market[market_id] = matches
            self.last_frame_kind = "odds"
        else:
            self.last_frame_kind = "ignored"

        return matches

    async def resubscribe_all(self):
        """
        Lightweight recovery: re-send subscribe messages on the SAME
        websocket. Used when heartbeats are still flowing but odds have
        gone quiet -- does not open a new socket or re-fetch REST.
        """
        sent = 0
        for market_id in list(self._subscribed_ids):
            market = self._catalogue.get(market_id)
            if not market:
                continue
            event = market.get("event") or {}
            event_id = event.get("id")
            if not event_id:
                continue
            await self.client.subscribe(market_id, event_id)
            sent += 1
        return sent

    async def close(self):
        self._closed = True

        task = self._catalogue_task
        self._catalogue_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        try:
            await self.client.close()
        except Exception:
            pass
