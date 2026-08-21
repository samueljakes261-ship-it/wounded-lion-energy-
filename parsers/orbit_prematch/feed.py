"""Orbit prematch session: upcoming REST catalogue + persistent SockJS.

Reuses parsers.orbit.client / parser (read-only) so BACK comes from
bdatb index 0 and LAY from bdatl index 0 -- never from a raw numeric
field named "odds". Live feed.py is not imported or modified.
"""

import asyncio
import time

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.client import OrbitWebSocketClient, is_orbit_heartbeat
from parsers.orbit.parser import OrbitParser
from parsers.orbit_prematch.catalogue import (
    _implied_ok,
    normalize_prematch_market,
)
from parsers.orbit_prematch.rest import get_upcoming_markets


CATALOGUE_REFRESH_SECONDS = 90
SOCKET_SILENCE_SECONDS = 60


def _tag_prematch(matches):
    tagged = []
    for match in matches:
        match.feed_type = "prematch"
        tagged.append(match)
    return tagged


class OrbitPrematchFeed:
    def __init__(self):
        self.client = OrbitWebSocketClient()
        self._catalogue = {}
        self._matches_by_market = {}
        self._subscribed_ids = set()
        self._runner_ladders = {}
        self._catalogue_task = None
        self._last_catalogue_refresh = 0.0
        self._last_activity_at = None
        self._closed = False
        self._inspected_frames = 0
        self.last_frame_kind = "ignored"
        self.frame_count = 0
        self.back_count = 0
        self.lay_count = 0
        self.stats = {
            "rest_markets": 0,
            "ws_frames": 0,
            "ws_odds_frames": 0,
            "ws_unknown_market": 0,
            "parse_rejected": 0,
            "implied_rejected": 0,
            "valid_matchodds": 0,
        }

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

    def _inspect_frame(self, raw):
        if self._inspected_frames >= 3 or not isinstance(raw, dict):
            return
        self._inspected_frames += 1
        rc = raw.get("rc") or []
        sample = rc[0] if rc else {}
        print(
            "[ORBIT PREMATCH] frame keys="
            f"{sorted(raw.keys())} rc_keys={sorted(sample.keys()) if isinstance(sample, dict) else []}"
        )
        if "bdatb" in sample or "bdatl" in sample:
            print(
                "[ORBIT PREMATCH] BACK/LAY identified via bdatb/bdatl "
                "(index 0 = best price); not using a generic odds field"
            )

    async def connect_and_subscribe(self):
        print("[ORBIT PREMATCH] session started (REST catalogue + persistent websocket)")
        print("[ORBIT PREMATCH] fetching today/tomorrow/future catalogues...")
        markets = await asyncio.to_thread(get_upcoming_markets)
        for market in markets:
            market = normalize_prematch_market(market)
            if not (market.get("event") or {}).get("homeTeam"):
                self.stats["parse_rejected"] += 1
                print(
                    "[PREMATCH][ORBIT] skip catalogue market "
                    f"{market.get('marketId')}: missing home/away identity"
                )
                continue
            self._catalogue[market["marketId"]] = market
        self.stats["rest_markets"] = len(self._catalogue)
        self._last_catalogue_refresh = time.monotonic()
        await self.client.connect()
        print(f"[ORBIT PREMATCH] websocket connected")
        print(f"[ORBIT PREMATCH] subscribing to {len(self._catalogue)} prematch markets...")
        for market in self._catalogue.values():
            event = market.get("event") or {}
            await self.client.subscribe(market["marketId"], event.get("id"))
            self._subscribed_ids.add(market["marketId"])
        self._closed = False
        if self._catalogue_task is None or self._catalogue_task.done():
            self._catalogue_task = asyncio.create_task(
                self._catalogue_refresh_loop(),
                name="orbit-prematch-catalogue-refresh",
            )
        return len(self._catalogue)

    async def _catalogue_refresh_loop(self):
        try:
            await asyncio.sleep(CATALOGUE_REFRESH_SECONDS)
        except asyncio.CancelledError:
            raise
        while not self._closed:
            try:
                added = await self._refresh_catalogue()
                if added:
                    print(
                        f"[ORBIT PREMATCH] catalogue refresh: +{added} "
                        f"(total {len(self._subscribed_ids)})"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(
                    f"[ORBIT PREMATCH] catalogue refresh failed "
                    f"({type(exc).__name__}: {exc}); session continues"
                )
            try:
                await asyncio.sleep(CATALOGUE_REFRESH_SECONDS)
            except asyncio.CancelledError:
                raise

    async def _refresh_catalogue(self):
        markets = await asyncio.to_thread(get_upcoming_markets)
        self._last_catalogue_refresh = time.monotonic()
        new_count = 0
        for market in markets:
            market = normalize_prematch_market(market)
            market_id = market["marketId"]
            if not (market.get("event") or {}).get("homeTeam"):
                continue
            self._catalogue[market_id] = market
            if market_id in self._subscribed_ids:
                continue
            event = market.get("event") or {}
            await self.client.subscribe(market_id, event.get("id"))
            self._subscribed_ids.add(market_id)
            new_count += 1
        return new_count

    async def receive_next(self):
        raw = await asyncio.wait_for(
            self.client.receive(),
            timeout=SOCKET_SILENCE_SECONDS,
        )
        self._last_activity_at = time.monotonic()
        self.frame_count += 1
        self.stats["ws_frames"] += 1
        if raw is None:
            self.last_frame_kind = "ignored"
            raise ConnectionError("Orbit prematch websocket closed by server.")
        if is_orbit_heartbeat(raw):
            self.last_frame_kind = "heartbeat"
            return []
        if not isinstance(raw, dict) or "id" not in raw:
            self.last_frame_kind = "ignored"
            return []
        self._inspect_frame(raw)
        market_id = raw["id"]
        if market_id not in self._catalogue:
            self.last_frame_kind = "ignored"
            self.stats["ws_unknown_market"] += 1
            return []
        try:
            parsed = OrbitParser.parse(
                raw,
                self._catalogue[market_id],
                runner_cache=self._runner_ladders,
            )
            matches = _tag_prematch(OrbitAdapter.to_match_odds_both_sides(parsed))
        except (KeyError, ValueError, TypeError) as exc:
            print(
                f"[ORBIT PREMATCH] skipping market {market_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            self.last_frame_kind = "ignored"
            self.stats["parse_rejected"] += 1
            return []
        kept = []
        for match in matches:
            # BACK 1X2 books have overround >= ~1.0. LAY books sit
            # below 1.0 by design (the exchange spread). Do not apply
            # the BACK overround guard to LAY.
            if match.side == "BACK" and not _implied_ok(
                match.home_odds, match.draw_odds, match.away_odds
            ):
                print(
                    "[PREMATCH][ORBIT][REJECT] "
                    f"event={match.home_team} vs {match.away_team} "
                    f"side={match.side} "
                    f"HOME={match.home_odds} DRAW={match.draw_odds} "
                    f"AWAY={match.away_odds} reason=implied_sum_not_1X2_book"
                )
                self.stats["implied_rejected"] += 1
                continue
            kept.append(match)
        matches = kept
        if matches:
            self._matches_by_market[market_id] = matches
            self.last_frame_kind = "odds"
            self.stats["ws_odds_frames"] += 1
            self.stats["valid_matchodds"] = len(self.get_match_odds())
            self.back_count = sum(
                1 for item in self.get_match_odds() if item.side == "BACK"
            )
            self.lay_count = sum(
                1 for item in self.get_match_odds() if item.side == "LAY"
            )
        else:
            self.last_frame_kind = "ignored"
        return matches

    async def resubscribe_all(self):
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
