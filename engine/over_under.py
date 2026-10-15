"""Two-way Over/Under 2.5 arbitrage, isolated from 3-way 1X2."""

from models.markets import TARGET_OU_LINE, is_over_under_market, line_key
from models.over_under import OverUnderOpportunity
from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError


def calculate_two_way_stakes(over_odds, under_odds, bankroll):
    implied = (1 / over_odds) + (1 / under_odds)
    target_return = bankroll / implied
    over_stake = round(target_return / over_odds, 2)
    under_stake = round(target_return / under_odds, 2)
    guaranteed_profit = round(target_return - bankroll, 2)
    roi = round((guaranteed_profit / bankroll) * 100, 2)
    return {
        "over_stake": over_stake,
        "under_stake": under_stake,
        "total_stake": round(bankroll, 2),
        "guaranteed_return": round(target_return, 2),
        "guaranteed_profit": guaranteed_profit,
        "roi": roi,
        "implied": implied,
    }


def build_over_under_opportunities(matched_events, bankroll=1000):
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    opportunities = []
    for event in matched_events:
        if not is_over_under_market(event.market):
            continue
        line = line_key(event.matches[0]) if event.matches else None
        if line != TARGET_OU_LINE:
            continue
        try:
            best = selector.select_over_under(event)
        except NoBackableOddsError:
            continue
        implied, exists, profit = detector.detect_two_way(
            best.over_odds, best.under_odds
        )
        if not exists:
            continue
        if best.over_match.bookmaker == best.under_match.bookmaker:
            continue
        stakes = calculate_two_way_stakes(best.over_odds, best.under_odds, bankroll)
        feed = getattr(event.matches[0], "feed_type", "live") if event.matches else "live"
        opportunities.append(
            OverUnderOpportunity(
                event=event,
                best=best,
                line=line,
                implied_probability=implied,
                profit_percentage=profit,
                over_stake=stakes["over_stake"],
                under_stake=stakes["under_stake"],
                total_stake=stakes["total_stake"],
                guaranteed_return=stakes["guaranteed_return"],
                guaranteed_profit=stakes["guaranteed_profit"],
                roi=stakes["roi"],
                feed_type=feed,
            )
        )
    return opportunities
