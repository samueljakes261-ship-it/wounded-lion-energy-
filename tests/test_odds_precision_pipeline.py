"""
Issue 1 regression coverage: odds must be preserved bit-for-bit
(no rounding/truncation) from raw bookmaker response through parsing,
engine selection, and the cache file api.py serves verbatim.

These tests use deliberately "awkward" precision values (more than 2
decimal places) specifically to catch any rounding introduced anywhere
in the pipeline -- 2 decimal places would silently pass even a buggy
`round(x, 2)` inserted by accident.
"""

import json

from datetime import datetime, timezone

import collector
from engine.best_odds_selector import BestOddsSelector
from engine.arbitrage_detector import ArbitrageDetector
from engine.stake_calculator import StakeCalculator
from engine.match_finder import MatchFinder
from models.arbitrage_opportunity import ArbitrageOpportunity
from models.match import MatchOdds
from parsers.betkanyon.parser import parse_json as betkanyon_parse_json
from parsers.betkanyon.adapter import BetkanyonAdapter
from parsers.onwin.parser import extract_1x2_market
from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.parser import OrbitParser


NOW = datetime.now(timezone.utc)


# ----------------------------------------------------------------------
# 1 & 2. Parsed odds equal the source bookmaker odds, for every
# bookmaker in the live pipeline.
# ----------------------------------------------------------------------

def test_betkanyon_parser_preserves_awkward_precision():
    raw = {
        "CNT": [
            {
                "CL": [
                    {
                        "EGN": "Test League",
                        "E": [
                            {
                                "Id": 1,
                                "EHT": "Home FC",
                                "EAT": "Away FC",
                                "D": "2026-01-01T12:00:00Z",
                                "StakeTypes": [
                                    {
                                        "Id": 1,
                                        "Stakes": [
                                            {"SN": "1", "F": "2.157"},
                                            {"SN": "X", "F": "3.409"},
                                            {"SN": "2", "F": "2.881"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }

    matches = betkanyon_parse_json(raw)

    assert len(matches) == 1
    assert matches[0]["home_odds"] == 2.157
    assert matches[0]["draw_odds"] == 3.409
    assert matches[0]["away_odds"] == 2.881


def test_betkanyon_adapter_does_not_alter_parsed_odds():
    event = {
        "competition": "Test League",
        "sport": "football",
        "home": "Home FC",
        "away": "Away FC",
        "kickoff": "2026-01-01T12:00:00Z",
        "home_odds": 2.157,
        "draw_odds": 3.409,
        "away_odds": 2.881,
    }

    match = BetkanyonAdapter.to_match_odds(event)

    assert match.home_odds == 2.157
    assert match.draw_odds == 3.409
    assert match.away_odds == 2.881


def test_onwin_extract_1x2_market_preserves_awkward_precision():
    event = {
        "scopes": {
            "normal_time--0": {
                "markets": {
                    "score_1x2--nil": {
                        "outcomes": {
                            "outcome::p1": {"coefficient": 1.913, "updatedAt": 1},
                            "outcome::draw": {"coefficient": 3.667, "updatedAt": 1},
                            "outcome::p2": {"coefficient": 4.021, "updatedAt": 1},
                        }
                    }
                }
            }
        }
    }

    home_odds, draw_odds, away_odds, _ = extract_1x2_market(event)

    assert home_odds == 1.913
    assert draw_odds == 3.667
    assert away_odds == 4.021


def test_orbit_adapter_preserves_awkward_precision():
    from parsers.orbit.models import MarketOdds, RunnerOdds

    def ladder(odds):
        return [{"index": 0, "odds": odds, "amount": 5}]

    market = MarketOdds(
        market_id="1.1", event_id="1", market_status="OPEN", in_play=True,
        runners=[
            RunnerOdds(1, name="Home FC", back=ladder(1.879), lay=[], traded_volume=0),
            RunnerOdds(2, name="Away FC", back=ladder(4.213), lay=[], traded_volume=0),
            RunnerOdds(3, name="The Draw", back=ladder(3.552), lay=[], traded_volume=0),
        ],
        home_team="Home FC", away_team="Away FC",
        competition="Test League", sport="Soccer",
        market_name="Match Odds", start_time=1_700_000_000_000,
        total_matched=0.0,
    )

    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match.home_odds == 1.879
    assert match.away_odds == 4.213
    assert match.draw_odds == 3.552


# ----------------------------------------------------------------------
# 3. Internal arbitrage calculations use the unrounded odds.
# ----------------------------------------------------------------------

def test_engine_uses_full_precision_not_a_rounded_copy():
    home = MatchOdds(
        bookmaker="OnWin", competition="X", sport="football", market="1X2",
        home_team="A", away_team="B",
        home_odds=2.101, draw_odds=3.001, away_odds=3.999,
        start_time=NOW, collected_at=NOW,
    )
    other = MatchOdds(
        bookmaker="Betkanyon", competition="X", sport="football", market="1X2",
        home_team="A", away_team="B",
        home_odds=1.500, draw_odds=3.601, away_odds=4.501,
        start_time=NOW, collected_at=NOW,
    )

    event = MatchFinder().find([home, other])[0]
    best = BestOddsSelector().select(event)

    # The odds carried into ArbitrageDetector must be the EXACT
    # dataclass values, not a rounded/reformatted copy.
    assert best.home_odds == 2.101
    assert best.draw_odds == 3.601
    assert best.away_odds == 4.501

    result = ArbitrageDetector().detect(best)
    expected_implied = (1 / 2.101) + (1 / 3.601) + (1 / 4.501)
    assert result.implied_probability == expected_implied


# ----------------------------------------------------------------------
# 4 & 6. API/cache output returns the correct, full-precision odds
# (only derived metrics like profitPercentage are ever rounded).
# ----------------------------------------------------------------------

def test_cache_write_preserves_exact_odds_and_rounds_only_derived_metrics(tmp_path, monkeypatch):
    cache_file = tmp_path / "cached_opportunities.json"
    monkeypatch.setattr(collector, "CACHE_FILE", cache_file)

    home = MatchOdds(
        bookmaker="OnWin", competition="X", sport="football", market="1X2",
        home_team="A", away_team="B",
        home_odds=2.10123, draw_odds=3.00456, away_odds=4.00789,
        start_time=NOW, collected_at=NOW,
    )
    other = MatchOdds(
        bookmaker="Betkanyon", competition="X", sport="football", market="Match Odds",
        home_team="A", away_team="B",
        home_odds=1.50111, draw_odds=3.60222, away_odds=4.50333,
        start_time=NOW, collected_at=NOW,
    )

    event = MatchFinder().find([home, other])[0]
    best = BestOddsSelector().select(event)
    result = ArbitrageDetector().detect(best)
    stake_plan = StakeCalculator().calculate(result=result, bankroll=1000)

    opportunity = ArbitrageOpportunity(event=event, result=result, stake_plan=stake_plan)

    collector._write_cache([opportunity], generated_at_dt=NOW)

    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert len(cached) == 1
    entry = cached[0]

    # Odds themselves: EXACT, full precision, never rounded/truncated.
    assert entry["home"]["odds"] == 2.10123
    assert entry["draw"]["odds"] == 3.60222
    assert entry["away"]["odds"] == 4.50333

    # Derived percentage/probability metrics ARE intentionally rounded
    # for display -- these are not "odds" and rounding them does not
    # affect what the engine used internally to decide arbitrage.
    assert entry["profitPercentage"] == round(result.profit_percentage, 2)
    assert entry["impliedProbability"] == round(result.implied_probability, 4)


def test_cache_entries_carry_full_traceability_metadata(tmp_path, monkeypatch):
    """Every opportunity must carry enough metadata to determine
    bookmaker, event, market, selection, odds, and collection/
    processing timestamps (Issue 1 requirement)."""

    cache_file = tmp_path / "cached_opportunities.json"
    monkeypatch.setattr(collector, "CACHE_FILE", cache_file)

    home = MatchOdds(
        bookmaker="OnWin", competition="X", sport="football", market="1X2",
        home_team="A", away_team="B",
        home_odds=2.10, draw_odds=3.00, away_odds=4.00,
        start_time=NOW, collected_at=NOW,
    )
    other = MatchOdds(
        bookmaker="Betkanyon", competition="X", sport="football", market="Match Odds",
        home_team="A", away_team="B",
        home_odds=1.50, draw_odds=3.60, away_odds=4.50,
        start_time=NOW, collected_at=NOW,
    )

    event = MatchFinder().find([home, other])[0]
    best = BestOddsSelector().select(event)
    result = ArbitrageDetector().detect(best)
    stake_plan = StakeCalculator().calculate(result=result, bankroll=1000)
    opportunity = ArbitrageOpportunity(event=event, result=result, stake_plan=stake_plan)

    collector._write_cache([opportunity], generated_at_dt=NOW)

    entry = json.loads(cache_file.read_text(encoding="utf-8"))[0]

    assert entry["generatedAt"] is not None

    for leg in ("home", "draw", "away"):
        assert entry[leg]["bookmaker"]
        assert entry[leg]["odds"] is not None
        assert entry[leg]["market"]
        assert entry[leg]["collectedAt"] is not None
        assert "stake" in entry[leg]

    assert entry["homeTeam"] == "A"
    assert entry["awayTeam"] == "B"
    assert entry["market"] == "1X2"


def test_json_round_trip_does_not_change_odds_value():
    """Sanity guard: JSON serialization itself (used both by the cache
    file and by FastAPI's response) must not alter the float value --
    proves the "API stage" and "frontend receives" stage are identical
    to what the engine computed."""

    value = 2.10123456789
    round_tripped = json.loads(json.dumps({"odds": value}))["odds"]
    assert round_tripped == value
