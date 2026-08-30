from datetime import datetime, timezone

from debug import odds_trace
from models.match import MatchOdds


class OrbitAdapter:

    # Top-of-book price for a side comes from Orbit's "bdatb"/"bdatl"
    # ladders: a list of {"index", "odds", "amount"} dicts where Orbit
    # itself explicitly marks "index" 0 as the best price for that
    # side. See parsers/orbit/parser.py for why the older "catb"/
    # "catl" [price, size] arrays are not used here -- they are sorted
    # by ascending numeric price, which is NOT the same as "best price
    # first" for BACK (best back = highest price).
    _SIDE_ATTR = {
        "BACK": "back",
        "LAY": "lay",
    }

    @staticmethod
    def _top_price(runner, side):
        ladder = getattr(runner, OrbitAdapter._SIDE_ATTR[side])

        if not ladder:
            return None

        # odds <= 0 is Orbit's placeholder for "no quote at this
        # depth" (a runner with no liquidity on this side still sends
        # 3 entries with odds=0.0/amount=0.0 rather than omitting
        # them) -- it must not be treated as a real price.
        quoted = [level for level in ladder if level.get("odds", 0) > 0]

        if not quoted:
            return None

        best = min(quoted, key=lambda level: level["index"])

        return best["odds"]

    @staticmethod
    def _find_by_team_name(runners, team_name):
        if not team_name:
            return None

        target = team_name.strip().lower()

        for runner in runners:
            if runner.name and runner.name.strip().lower() == target:
                return runner

        return None

    @staticmethod
    def _split_home_draw_away(market):
        """
        Identify which runner is home/draw/away by matching runner
        NAME against the catalogue's home/away team names -- never by
        array position.

        Orbit's runner order is NOT guaranteed to be [home, draw,
        away]: live observation across many markets shows it is
        actually [home, away, draw] (the Draw selection, id 58805,
        consistently comes last). Unpacking positionally as
        `home, draw, away = market.runners` silently swapped the draw
        and away runners' odds with each other. Name-matching
        sidesteps the ordering question entirely: whichever runner
        isn't identified as home or away is the draw, regardless of
        where it sits in the list.

        Returns (home, draw, away) RunnerOdds, or (None, None, None)
        if home/away can't be unambiguously identified (e.g. missing
        runner name, or this isn't actually a classic 1X2 market).
        """

        if len(market.runners) != 3:
            return None, None, None

        home = OrbitAdapter._find_by_team_name(
            market.runners, market.home_team
        )
        away = OrbitAdapter._find_by_team_name(
            market.runners, market.away_team
        )

        if home is None or away is None or home is away:
            return None, None, None

        remaining = [
            runner for runner in market.runners
            if runner is not home and runner is not away
        ]

        if len(remaining) != 1:
            return None, None, None

        return home, remaining[0], away

    @staticmethod
    def to_match_odds(market, side="BACK"):
        """
        Build one MatchOdds for one side (BACK or LAY) of this market.

        A LAY price is NOT a normal bookmaker price -- it is tagged
        with side="LAY" so the arbitrage engine's best_odds_selector
        never silently treats it as an ordinary BACK price (see
        engine/best_odds_selector.py). Returns None if this market
        isn't a classic 3-runner 1-X-2 market, if home/draw/away can't
        be unambiguously identified by name, or if any of the three
        runners has no quoted price on the requested side yet.
        """

        if side not in OrbitAdapter._SIDE_ATTR:
            raise ValueError(f"Unknown Orbit side: {side!r}")

        home, draw, away = OrbitAdapter._split_home_draw_away(market)

        if home is None:
            return None

        home_odds = OrbitAdapter._top_price(home, side)
        draw_odds = OrbitAdapter._top_price(draw, side)
        away_odds = OrbitAdapter._top_price(away, side)

        if home_odds is None or draw_odds is None or away_odds is None:
            return None

        # Orbit's "odds" fields are already JSON numbers (no string
        # parsing involved), so RAW and PARSED are identical here --
        # traced anyway for a consistent RAW->PARSED->ENGINE->API view
        # across all three bookmakers.
        odds_trace.record(
            "PARSED",
            "Orbit",
            market.home_team,
            market.away_team,
            market.market_name,
            side,
            home_odds,
            draw_odds,
            away_odds,
        )

        return MatchOdds(

            bookmaker="Orbit",

            competition=market.competition,

            sport=market.sport,

            market=market.market_name,

            home_team=market.home_team,

            away_team=market.away_team,

            home_odds=home_odds,

            draw_odds=draw_odds,

            away_odds=away_odds,

            start_time=datetime.fromtimestamp(
                market.start_time / 1000,
                tz=timezone.utc,
            ),

            # Timezone-aware (UTC), matching BetKanyon/OnWin, so
            # collector.py can safely compute freshness/age across all
            # three bookmakers without a naive/aware datetime mismatch.
            collected_at=datetime.now(timezone.utc),

            side=side,
        )

    @staticmethod
    def to_match_odds_both_sides(market):
        """
        Convenience helper: returns a list with up to two MatchOdds --
        one BACK-side and one LAY-side -- for this market, omitting
        whichever side isn't fully quoted yet.
        """

        result = []

        for side in ("BACK", "LAY"):
            match = OrbitAdapter.to_match_odds(market, side=side)
            if match is not None:
                result.append(match)

        return result