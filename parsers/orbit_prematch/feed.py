"""Orbit prematch session: upcoming REST catalogue + persistent SockJS.

Reuses parsers.orbit.client / parser (read-only) so BACK comes from
bdatb index 0 and LAY from bdatl index 0 -- never from a raw numeric
field named "odds". Live feed.py is not imported or modified.
"""

import asyncio
import time

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.client import is_orbit_heartbeat
from parsers.orbit.parser import OrbitParser
from parsers.orbit_prematch.catalogue import (
    _implied_ok,
    normalize_prematch_market,
)
from parsers.orbit_prematch.client import OrbitPrematchWebSocketClient
from parsers.orbit_prematch.rest import (
    TABS,
    _fetch_tab,
    _fetch_tab_first_page,
    _fetch_tab_remaining,
    get_upcoming_markets,
)


CATALOGUE_REFRESH_SECONDS = 180
SOCKET_SILENCE_SECONDS = 90
SUBSCRIBE_YIELD_EVERY = 25


def _tag_prematch(matches):
    tagged = []
    for match in matches:
        match.feed_type = "prematch"
        tagged.append(match)
    return tagged


class OrbitPrematchFeed:
    def __init__(self):
        self.client = OrbitPrematchWebSocketClient()
        self._catalogue = {}
        self._matches_by_market = {}
        self._subscribed_ids = set()
        self._runner_ladders = {}
        self._catalogue_task = None
        self._bootstrap_task = None
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

    async def _ingest_markets(self, markets):
        added = 0
        skipped = 0
        for market in markets:
            market = normalize_prematch_market(market)
            market_id = market.get("marketId")
            if not market_id:
                skipped += 1
                continue
            if not (market.get("event") or {}).get("homeTeam"):
                self.stats["parse_rejected"] += 1
                skipped += 1
                print(
                    "[PREMATCH][ORBIT] skip catalogue market "
                    f"{market_id}: missing home/away identity"
                )
                continue
            self._catalogue[market_id] = market
            if market_id in self._subscribed_ids:
                continue
            event = market.get("event") or {}
            event_id = event.get("id")
            if not event_id:
                skipped += 1
                continue
            await self.client.subscribe(market_id, event_id)
            self._subscribed_ids.add(market_id)
            added += 1
            if added % SUBSCRIBE_YIELD_EVERY == 0:
                await asyncio.sleep(0)
        self.stats["rest_markets"] = len(self._catalogue)
        return added, skipped

    async def connect_and_subscribe(self):
        print("[ORBIT PREMATCH] session started (REST catalogue + persistent websocket)")
        print("[ORBIT PREMATCH] connecting websocket while fetching TODAY page 0...")
        ws_task = asyncio.create_task(self.client.connect())
        try:
            first_markets, first_stats = await asyncio.to_thread(
                _fetch_tab_first_page, "TODAY"
            )
            await ws_task
        except Exception:
            if not ws_task.done():
                ws_task.cancel()
            try:
                await ws_task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        print("[ORBIT PREMATCH] websocket connected")
        added, _skipped = await self._ingest_markets(first_markets)
        print(
            f"[ORBIT PREMATCH] today page0 unique +{added} "
            f"(subscribed {len(self._subscribed_ids)}); "
            "price feed starting while remaining catalogue loads"
        )
        self._last_catalogue_refresh = time.monotonic()
        self._closed = False
        if self._bootstrap_task is None or self._bootstrap_task.done():
            self._bootstrap_task = asyncio.create_task(
                self._bootstrap_remaining_catalogue(first_stats),
                name="orbit-prematch-bootstrap-tabs",
            )
        return len(self._catalogue)

    async def _bootstrap_remaining_catalogue(self, first_stats):
        try:
            remaining_today = first_stats.get("remaining_pages") or []
            if remaining_today and not self._closed:
                markets, stats = await asyncio.to_thread(
                    _fetch_tab_remaining, "TODAY", remaining_today
                )
                added, _skipped = await self._ingest_markets(markets)
                print(
                    f"[ORBIT PREMATCH] today remaining unique +{added} "
                    f"(subscribed {len(self._subscribed_ids)})"
                )
                print(
                    "[PREMATCH][ORBIT] REST "
                    f"TODAY: raw={first_stats['raw'] + stats['raw']} "
                    f"kept={first_stats['kept'] + stats['kept']} "
                    f"unique_markets={len(self._catalogue)}"
                )
            for tab in TABS:
                if tab == "TODAY" or self._closed:
                    continue
                markets, stats = await asyncio.to_thread(_fetch_tab, tab)
                added, _skipped = await self._ingest_markets(markets)
                print(
                    f"[ORBIT PREMATCH] {tab.lower()} unique +{added} "
                    f"(subscribed {len(self._subscribed_ids)})"
                )
                print(
                    "[PREMATCH][ORBIT] REST "
                    f"{tab}: raw={stats['raw']} kept={stats['kept']} "
                    f"unique_markets={len(self._catalogue)}"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                f"[ORBIT PREMATCH] remaining-tab bootstrap failed "
                f"({type(exc).__name__}: {exc}); session continues"
            )
        if not self._closed and (
            self._catalogue_task is None or self._catalogue_task.done()
        ):
            self._catalogue_task = asyncio.create_task(
                self._catalogue_refresh_loop(),
                name="orbit-prematch-catalogue-refresh",
            )

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

    def has_catalogue(self):
        return bool(self._catalogue)

    async def reconnect_socket(self):
        """Replace only the websocket. Keep catalogue and last prices."""
        print("[ORBIT PREMATCH] reconnecting websocket (keeping catalogue)")
        old_client = self.client
        try:
            await old_client.close()
        except Exception:
            pass
        self.client = OrbitPrematchWebSocketClient()
        await self.client.connect()
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
            if sent % SUBSCRIBE_YIELD_EVERY == 0:
                await asyncio.sleep(0)
        print(
            f"[ORBIT PREMATCH] resubscribed {sent} cached markets "
            "after socket reconnect"
        )
        return sent

    async def _refresh_catalogue(self):
        markets = await asyncio.to_thread(get_upcoming_markets)
        self._last_catalogue_refresh = time.monotonic()
        added, _skipped = await self._ingest_markets(markets)
        return added

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
                self.stats["implied_rejected"] += 1
                if self.stats["implied_rejected"] <= 5 or self.stats["implied_rejected"] % 50 == 0:
                    print(
                        "[PREMATCH][ORBIT][REJECT] "
                        f"event={match.home_team} vs {match.away_team} "
                        f"side={match.side} "
                        f"HOME={match.home_odds} DRAW={match.draw_odds} "
                        f"AWAY={match.away_odds} reason=implied_sum_not_1X2_book"
                    )
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
            if sent % SUBSCRIBE_YIELD_EVERY == 0:
                await asyncio.sleep(0)
        return sent

    async def close(self):
        self._closed = True
        for attr in ("_bootstrap_task", "_catalogue_task"):
            task = getattr(self, attr, None)
            setattr(self, attr, None)
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
