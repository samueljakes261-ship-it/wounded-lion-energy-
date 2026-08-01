from models.arbitrage_result import ArbitrageResult
from models.bet_instruction import BetInstruction
from models.stake_plan import StakePlan


class StakeCalculator:
    """
    Calculates the optimal stake distribution
    for an arbitrage opportunity.
    """

    def calculate(
        self,
        result: ArbitrageResult,
        bankroll: float,
    ) -> StakePlan:

        if not result.arbitrage_exists:
            raise ValueError(
                "Cannot calculate stakes because no arbitrage exists."
            )

        best = result.best_odds

        implied_probability = result.implied_probability

        # Equal payout for every outcome
        target_return = bankroll / implied_probability

        home_stake = target_return / best.home_odds
        draw_stake = target_return / best.draw_odds
        away_stake = target_return / best.away_odds

        guaranteed_profit = target_return - bankroll

        roi = (guaranteed_profit / bankroll) * 100

        return StakePlan(

            home=BetInstruction(
                outcome="HOME",
                bookmaker=best.home_match.bookmaker,
                odds=best.home_odds,
                stake=round(home_stake, 2),
            ),

            draw=BetInstruction(
                outcome="DRAW",
                bookmaker=best.draw_match.bookmaker,
                odds=best.draw_odds,
                stake=round(draw_stake, 2),
            ),

            away=BetInstruction(
                outcome="AWAY",
                bookmaker=best.away_match.bookmaker,
                odds=best.away_odds,
                stake=round(away_stake, 2),
            ),

            total_stake=round(bankroll, 2),

            guaranteed_return=round(target_return, 2),

            guaranteed_profit=round(guaranteed_profit, 2),

            roi=round(roi, 2),
        )