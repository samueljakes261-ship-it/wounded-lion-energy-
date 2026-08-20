from engine.matcher import EventMatcher
from models.back_lay_opportunity import BackLayOpportunity
from models.match import MatchOdds


class BackLayDetector:
    """
    Detects a classic "back-lay" hedge: backing an outcome at a fixed
    price B on one bookmaker/exchange-back-side and laying the SAME
    outcome at price L on an exchange (Orbit), when B > L, guarantees
    a profit regardless of the match result for that one outcome.

    This is intentionally kept SEPARATE from ArbitrageDetector rather
    than folded into its formula. ArbitrageDetector's
    sum(1/odds) < 1 check assumes three legs, each a fixed-odds BACK
    bet on a DIFFERENT outcome of the same event. A back-lay hedge is
    two legs on the SAME outcome, one of which (the lay leg) has a
    liability rather than a fixed stake->payout multiple -- mixing the
    two into one formula would silently misrepresent the lay leg's
    risk (see models/match.py's `side` field and
    engine/best_odds_selector.py, which excludes LAY prices from the
    ordinary 3-way formula for the same reason).

    Stake-split derivation (equal profit whether the outcome occurs or
    not): with back stake S_b and lay stake S_l,

        outcome occurs:     profit = S_b*(B-1) - S_l*(L-1)
        outcome doesn't:    profit = S_l - S_b

    Setting these equal gives S_l = S_b * B / L, and substituting back
    in yields a guaranteed profit of S_b*(B-L)/L on total stake
    S_b*(B+L)/L, i.e. a clean closed-form profit percentage of
    (B - L) / (B + L) * 100, independent of the actual stake size.
    """

    OUTCOME_FIELDS = {
        "HOME": "home_odds",
        "DRAW": "draw_odds",
        "AWAY": "away_odds",
    }

    def __init__(self):
        self.matcher = EventMatcher()

    def find(self, matches: list[MatchOdds]) -> list[BackLayOpportunity]:

        lay_matches = [m for m in matches if m.side == "LAY"]
        back_matches = [m for m in matches if m.side != "LAY"]

        opportunities = []

        for lay in lay_matches:
            for back in back_matches:

                if not self.matcher.is_same_event(back, lay):
                    continue

                for outcome, field in self.OUTCOME_FIELDS.items():

                    back_odds = getattr(back, field)
                    lay_odds = getattr(lay, field)

                    if back_odds <= lay_odds:
                        continue  # no guaranteed profit

                    profit_percentage = (
                        (back_odds - lay_odds)
                        / (back_odds + lay_odds)
                        * 100
                    )

                    opportunities.append(
                        BackLayOpportunity(
                            outcome=outcome,
                            sport=back.sport,
                            competition=back.competition,
                            home_team=back.home_team,
                            away_team=back.away_team,
                            back_bookmaker=back.bookmaker,
                            back_odds=back_odds,
                            lay_bookmaker=lay.bookmaker,
                            lay_odds=lay_odds,
                            profit_percentage=profit_percentage,
                        )
                    )

        return opportunities
