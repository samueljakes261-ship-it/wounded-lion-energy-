"""
Deterministic tests proving the existing engine (normalizer -> matcher
-> MatchFinder -> BestOddsSelector -> ArbitrageDetector ->
StakeCalculator) correctly consumes MatchOdds coming from OnWin,
BetKanyon, AND Orbit (BACK/LAY) at once.

These tests build MatchOdds fixtures directly rather than going through
either bookmaker's live feed -- the point is to prove the *combination*
and *engine* behavior deterministically, independent of network access.
At least one fixture contains a deliberate arbitrage opportunity so the
pipeline can be verified without depending on a real arbitrage existing
during a live run.
"""

from datetime import datetime, timezone

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from engine.match_finder import MatchFinder
from engine.stake_calculator import StakeCalculator
from models.match import MatchOdds


NOW = datetime.now(timezone.utc)


def onwin_match(home, away, home_odds, draw_odds, away_odds, competition="Test League"):
    return MatchOdds(
        bookmaker="OnWin",
        competition=competition,
        sport="football",
        market="1X2",
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
    )


def betkanyon_match(home, away, home_odds, draw_odds, away_odds, competition="Test League"):
    return MatchOdds(
        bookmaker="Betkanyon",
        competition=competition,
        sport="football",
        market="Match Odds",
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
    )


def orbit_match(home, away, home_odds, draw_odds, away_odds, side="BACK", competition="Test League"):
    return MatchOdds(
        bookmaker="Orbit",
        competition=competition,
        sport="football",
        market="Match Odds",
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
        side=side,
    )


def run_pipeline(matches, bankroll=1000):
    finder = MatchFinder()
    selector = BestOddsSelector()
    detector = ArbitrageDetector()
    calculator = StakeCalculator()

    opportunities = []

    for event in finder.find(matches):

        try:
            best = selector.select(event)
        except NoBackableOddsError:
            continue

        result = detector.detect(best)

        if not result.arbitrage_exists:
            continue

        stake_plan = calculator.calculate(result=result, bankroll=bankroll)
        opportunities.append((event, result, stake_plan))

    return opportunities


# ----------------------------------------------------------------------
# Deliberate arbitrage opportunity across OnWin + BetKanyon
# ----------------------------------------------------------------------

def test_deliberate_arbitrage_detected_across_onwin_and_betkanyon():
    """
    OnWin has the best home price, BetKanyon has the best draw AND away
    price. Combined implied probability is deliberately built to be
    < 1, independent of whether a real arbitrage happens to exist live.
    """

    onwin = onwin_match(
        "Manchester United", "Atlético Madrid",
        home_odds=2.10, draw_odds=3.00, away_odds=3.20,
    )

    # Same event, slightly different team-name spelling (accent +
    # abbreviation) so this genuinely exercises TeamNameNormalizer /
    # EventMatcher rather than relying on exact string equality.
    betkanyon = betkanyon_match(
        "Man Utd", "Atletico Madrid",
        home_odds=1.80, draw_odds=3.60, away_odds=4.50,
    )

    implied = (1 / 2.10) + (1 / 3.60) + (1 / 4.50)
    assert implied < 1, "fixture must contain a real arbitrage"

    matches = [onwin, betkanyon]

    opportunities = run_pipeline(matches)

    assert len(opportunities) == 1

    event, result, stake_plan = opportunities[0]

    assert len(event.matches) == 2  # both bookmakers matched to one event
    assert result.arbitrage_exists is True
    assert result.profit_percentage > 0

    # Correct bookmaker chosen per leg.
    assert stake_plan.home.bookmaker == "OnWin"
    assert stake_plan.home.odds == 2.10
    assert stake_plan.draw.bookmaker == "Betkanyon"
    assert stake_plan.draw.odds == 3.60
    assert stake_plan.away.bookmaker == "Betkanyon"
    assert stake_plan.away.odds == 4.50

    # Stake plan is internally consistent with the requested bankroll.
    assert stake_plan.total_stake == 1000
    assert stake_plan.guaranteed_profit > 0
    assert stake_plan.roi > 0


def test_fair_odds_produce_no_arbitrage():
    """Sanity check: realistic, non-arbitrage odds must NOT be reported
    as an opportunity just because two bookmakers were combined."""

    onwin = onwin_match(
        "Liverpool", "Chelsea",
        home_odds=2.00, draw_odds=3.30, away_odds=3.80,
    )
    betkanyon = betkanyon_match(
        "Liverpool", "Chelsea",
        home_odds=1.95, draw_odds=3.25, away_odds=3.70,
    )

    opportunities = run_pipeline([onwin, betkanyon])

    assert opportunities == []


def test_unmatched_single_bookmaker_events_do_not_crash_pipeline():
    """Events seen by only one bookmaker must flow through the
    pipeline harmlessly (no crash, no false-positive arbitrage)."""

    onwin_only = onwin_match(
        "Real Madrid", "Barcelona",
        home_odds=2.5, draw_odds=3.1, away_odds=2.9,
    )
    betkanyon_only = betkanyon_match(
        "Bayern Munich", "Dortmund",
        home_odds=1.9, draw_odds=3.4, away_odds=4.0,
    )

    opportunities = run_pipeline([onwin_only, betkanyon_only])

    # Neither event has a second bookmaker to arbitrage against with
    # these single-sided odds, so nothing should be reported.
    assert opportunities == []


def test_multiple_events_only_matching_ones_combine():
    """With a mix of a matched pair and two unrelated single-bookmaker
    events, MatchFinder must only group the matched pair together."""

    matched_onwin = onwin_match(
        "Manchester United", "Atlético Madrid",
        home_odds=2.10, draw_odds=3.00, away_odds=3.20,
    )
    matched_betkanyon = betkanyon_match(
        "Man Utd", "Atletico Madrid",
        home_odds=1.80, draw_odds=3.60, away_odds=4.50,
    )
    unrelated_onwin = onwin_match(
        "Real Madrid", "Barcelona",
        home_odds=2.5, draw_odds=3.1, away_odds=2.9,
    )
    unrelated_betkanyon = betkanyon_match(
        "Bayern Munich", "Dortmund",
        home_odds=1.9, draw_odds=3.4, away_odds=4.0,
    )

    finder = MatchFinder()
    matched_events = finder.find([
        matched_onwin, matched_betkanyon, unrelated_onwin, unrelated_betkanyon,
    ])

    assert len(matched_events) == 3  # 1 matched pair + 2 standalone events

    sizes = sorted(len(event.matches) for event in matched_events)
    assert sizes == [1, 1, 2]

    opportunities = run_pipeline([
        matched_onwin, matched_betkanyon, unrelated_onwin, unrelated_betkanyon,
    ])

    assert len(opportunities) == 1
    event, _, _ = opportunities[0]
    assert {m.bookmaker for m in event.matches} == {"OnWin", "Betkanyon"}


# ----------------------------------------------------------------------
# Orbit participation: BACK odds combine normally, LAY odds never
# silently masquerade as a normal bookmaker BACK price.
# ----------------------------------------------------------------------

def test_orbit_back_participates_in_three_way_arbitrage():
    """
    BetKanyon has the best home price, Orbit's BACK price has the best
    draw AND away price -- a genuine three-bookmaker (well, two here)
    combination that must work exactly like the OnWin+BetKanyon case.
    """

    betkanyon = betkanyon_match(
        "Liverpool", "Chelsea",
        home_odds=2.30, draw_odds=3.00, away_odds=3.00,
    )
    orbit_back = orbit_match(
        "Liverpool", "Chelsea",
        home_odds=1.90, draw_odds=3.80, away_odds=4.20,
        side="BACK",
    )

    implied = (1 / 2.30) + (1 / 3.80) + (1 / 4.20)
    assert implied < 1, "fixture must contain a real arbitrage"

    opportunities = run_pipeline([betkanyon, orbit_back])

    assert len(opportunities) == 1
    event, result, stake_plan = opportunities[0]

    assert result.arbitrage_exists is True
    assert stake_plan.home.bookmaker == "Betkanyon"
    assert stake_plan.draw.bookmaker == "Orbit"
    assert stake_plan.away.bookmaker == "Orbit"


def test_orbit_lay_never_wins_best_odds_over_a_real_back_price():
    """
    Orbit's LAY price is numerically higher than BetKanyon's BACK price
    for every outcome -- if LAY were ever compared as if it were a
    normal BACK price, max(odds) would incorrectly select it and
    report a fake arbitrage. It must not.
    """

    betkanyon = betkanyon_match(
        "Liverpool", "Chelsea",
        home_odds=2.00, draw_odds=3.20, away_odds=3.60,
    )
    orbit_lay = orbit_match(
        "Liverpool", "Chelsea",
        home_odds=9.00, draw_odds=9.00, away_odds=9.00,  # absurdly high LAY
        side="LAY",
    )

    opportunities = run_pipeline([betkanyon, orbit_lay])

    # The LAY-side numbers would trivially produce a "3.3x profit"
    # arbitrage if fed into the ordinary formula -- correct behavior is
    # that Orbit's LAY entry is excluded entirely from best-odds
    # selection, leaving only BetKanyon's single-bookmaker (fair) odds.
    assert opportunities == []


def test_event_with_only_orbit_lay_odds_is_skipped_not_crashed():
    """An event seen ONLY via an Orbit LAY quote (no bookmaker/BACK
    price at all) must be skipped gracefully, not raise out of the
    pipeline."""

    orbit_lay_only = orbit_match(
        "Napoli", "Roma",
        home_odds=2.10, draw_odds=3.30, away_odds=3.50,
        side="LAY",
    )

    opportunities = run_pipeline([orbit_lay_only])

    assert opportunities == []
