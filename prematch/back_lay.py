"""Prematch BACK-vs-LAY detector.

Kept separate from:
  - engine/arbitrage_detector.py (3-way BACK-vs-BACK)
  - engine/back_lay_detector.py (live BACK-vs-LAY, EventMatcher)

This detector never infers BACK/LAY from numeric prices. It only
compares an explicit BACK leg against an explicit LAY leg after
PrematchMatchFinder has grouped the same prematch event.

Profitability (no commission configured in this repo):

    BACK price > LAY price  on the same event, market, outcome, feed

If an exchange commission rate is added later, apply it in
`_is_profitable` before accepting a candidate. Do not invent a rate.
"""

from models.back_lay_opportunity import (
    OPPORTUNITY_TYPE_BACK_LAY,
    BackLayOpportunity,
)
from prematch.matcher import PrematchMatchFinder


OUTCOME_FIELDS = {
    "HOME": "home_odds",
    "DRAW": "draw_odds",
    "AWAY": "away_odds",
}

_MARKET_ALIASES = {
    "1x2": "1x2",
    "match odds": "1x2",
    "matchodds": "1x2",
}

_MAX_REJECT_LOGS = 5


def _market_key(market) -> str:
    key = (market or "").strip().lower()
    return _MARKET_ALIASES.get(key, key)


def explicit_side(match) -> str:
    """Return BACK or LAY from the feed tag only -- never from the price."""
    raw = getattr(match, "side", None)
    if raw is None or str(raw).strip() == "":
        return "BACK"
    return str(raw).strip().upper()


def _feed_type(match) -> str:
    return getattr(match, "feed_type", "live") or "live"


def _is_profitable(back_odds: float, lay_odds: float) -> bool:
    """Raw BACK > LAY. Hook for future commission — none exists today."""
    return back_odds > lay_odds


def log_back_lay_decision(
    home_team,
    away_team,
    outcome,
    back_bookmaker,
    back_odds,
    lay_bookmaker,
    lay_odds,
    accepted,
    reason=None,
):
    print(f"[BACK-LAY] event={home_team} vs {away_team}")
    print(f"[BACK-LAY] outcome={outcome}")
    print(f"[BACK-LAY] BACK {back_bookmaker} @ {back_odds}")
    print(f"[BACK-LAY] LAY {lay_bookmaker} @ {lay_odds}")
    if accepted:
        print("[BACK-LAY] OPPORTUNITY")
    else:
        suffix = f" {reason}" if reason else ""
        print(f"[BACK-LAY] REJECTED{suffix}")


class PrematchBackLayDetector:
    def __init__(self):
        self.finder = PrematchMatchFinder()

    def find(self, matches, log=False) -> list[BackLayOpportunity]:
        events = self.finder.find(matches)
        opportunities = []
        rejected_logged = 0
        evaluated = 0
        accepted = 0

        for event in events:
            backs = [m for m in event.matches if explicit_side(m) == "BACK"]
            lays = [m for m in event.matches if explicit_side(m) == "LAY"]
            if not backs or not lays:
                continue

            for back in backs:
                for lay in lays:
                    if _feed_type(back) != _feed_type(lay):
                        continue
                    if _feed_type(back) != "prematch":
                        continue
                    if _market_key(back.market) != _market_key(lay.market):
                        continue

                    for outcome, field in OUTCOME_FIELDS.items():
                        back_odds = getattr(back, field)
                        lay_odds = getattr(lay, field)
                        evaluated += 1
                        if not _is_profitable(back_odds, lay_odds):
                            if log and rejected_logged < _MAX_REJECT_LOGS:
                                log_back_lay_decision(
                                    back.home_team,
                                    back.away_team,
                                    outcome,
                                    back.bookmaker,
                                    back_odds,
                                    lay.bookmaker,
                                    lay_odds,
                                    accepted=False,
                                    reason="back<=lay",
                                )
                                rejected_logged += 1
                            continue

                        accepted += 1
                        opp = BackLayOpportunity(
                            outcome=outcome,
                            sport=back.sport,
                            competition=back.competition,
                            home_team=back.home_team,
                            away_team=back.away_team,
                            back_bookmaker=back.bookmaker,
                            back_odds=back_odds,
                            lay_bookmaker=lay.bookmaker,
                            lay_odds=lay_odds,
                            opportunity_type=OPPORTUNITY_TYPE_BACK_LAY,
                            feed_type=_feed_type(back),
                            market=back.market,
                            back_side=explicit_side(back),
                            lay_side=explicit_side(lay),
                        )
                        if log:
                            log_back_lay_decision(
                                opp.home_team,
                                opp.away_team,
                                opp.outcome,
                                opp.back_bookmaker,
                                opp.back_odds,
                                opp.lay_bookmaker,
                                opp.lay_odds,
                                accepted=True,
                            )
                        opportunities.append(opp)

        if log:
            print(
                f"[BACK-LAY] evaluated={evaluated} "
                f"accepted={accepted} rejected={evaluated - accepted}"
            )
        return opportunities


def find_prematch_back_lay(matches, log=False) -> list[BackLayOpportunity]:
    return PrematchBackLayDetector().find(matches, log=log)


def serialize_back_lay_opportunities(opportunities) -> list[dict]:
    return [item.to_api_dict() for item in opportunities]
