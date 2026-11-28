import json

from .models import MarketOdds
from .models import RunnerOdds


class OrbitParser:

    @staticmethod
    def parse(message, catalogue, runner_cache=None):
        """
        Parse one Orbit websocket frame into a MarketOdds.

        runner_cache (optional): a caller-owned dict of
        selection_id -> {"back": [...], "lay": [...],
        "traded_volume": ...}, used to resolve a runner's price when
        THIS frame doesn't carry it.

        Orbit (like the Betfair-style exchange protocol it mirrors)
        only includes a runner in "rc" when that runner's own price
        actually changed -- a frame carries "img": true for a full
        snapshot (every runner present) but is otherwise a PARTIAL
        delta covering only the runner(s) that just moved. Without
        runner_cache, a runner absent from "rc" is built with empty
        back/lay ladders, which makes OrbitAdapter.to_match_odds()
        treat the whole market as "not fully quoted" and reject the
        frame -- so in production this silently froze every market at
        its last full-image snapshot the instant only ONE runner
        ticked, which is by far the common case for a live match.
        When runner_cache is provided, an absent runner (or an absent
        "bdatb"/"bdatl" key on a present runner) instead resolves to
        its last known price -- the same "absence means no new info,
        not no info at all" rule already used for OnWin (see
        parsers/onwin/state.py). Passing None preserves the previous,
        cache-free per-frame-only behavior (used by the manual
        diagnose_raw.py/live.py tools).
        """

        # websocket payload

        if isinstance(message, str):
            data = json.loads(message)
        else:
            data = message

        # "rc" entries carry price data only (no runner name) -- keyed
        # by selection id so it can be paired with the catalogue's
        # runner name/order below.
        live = {}

        for runner in data.get("rc", []):

            live[runner["id"]] = runner

        ordered = []

        for runner in catalogue["runners"]:

            sid = runner["selectionId"]

            rc = live.get(sid)

            cached = runner_cache.get(sid) if runner_cache is not None else None

            if rc is not None:

                # "bdatb"/"bdatl" ("book data available to back/lay")
                # each carry an explicit "index" (0 = best price for
                # that side) alongside "odds" and "amount" (liquidity
                # size) -- unlike "catb"/"catl", which are plain
                # [price, size] pairs sorted purely by ascending
                # numeric price. Ascending-by-price order means index 0
                # of "catb" is actually the WORST back price (best back
                # = highest price), so using it as "top price" silently
                # returned the wrong price level. "catl" happened to
                # look correct (ascending == best-first for LAY, since
                # best lay = lowest price) which is exactly the kind of
                # order-position assumption that must not be trusted --
                # see parsers/orbit/adapter.py.
                #
                # A key can be absent from an individual "rc" entry
                # even when the entry itself is present (e.g. only the
                # back side moved) -- fall back to that single side's
                # cached ladder rather than the whole runner's.
                back = (
                    rc["bdatb"] if "bdatb" in rc
                    else (cached.get("back", []) if cached else [])
                )
                lay = (
                    rc["bdatl"] if "bdatl" in rc
                    else (cached.get("lay", []) if cached else [])
                )
                traded_volume = rc.get(
                    "tv",
                    cached.get("traded_volume", 0) if cached else 0,
                )

                if runner_cache is not None:
                    runner_cache[sid] = {
                        "back": back,
                        "lay": lay,
                        "traded_volume": traded_volume,
                    }

            elif cached is not None:
                back = cached.get("back", [])
                lay = cached.get("lay", [])
                traded_volume = cached.get("traded_volume", 0)

            else:
                back = []
                lay = []
                traded_volume = 0

            ordered.append(

                RunnerOdds(

                    selection_id=sid,

                    name=runner.get("runnerName"),

                    back=back,

                    lay=lay,

                    traded_volume=traded_volume,

                )

            )

        definition = data.get("marketDefinition") or {}
        event = catalogue.get("event") or {}

        return MarketOdds(

            market_id=data["id"],

            event_id=definition.get("eventId") or event.get("id") or "",

            market_status=definition.get("status") or "OPEN",

            in_play=bool(definition.get("inPlay", True)),

            runners=ordered,

            home_team=catalogue["event"]["homeTeam"],

            away_team=catalogue["event"]["awayTeam"],

            competition=catalogue["competition"]["name"],

            sport=catalogue["eventType"]["name"],

            market_name=catalogue["marketName"],

            start_time=catalogue["marketStartTime"],

            total_matched=catalogue["totalMatched"],

        )