"""Prove this Kenyan-only change did not edit unrelated bookmaker packages."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

UNTOUCHED = [
    "parsers/betkanyon",
    "parsers/onwin",
    "parsers/orbit",
    "parsers/kolay90",
    "betfair",
    "engine/back_lay_detector.py",
    "engine/stake_calculator.py",
]


def test_unrelated_bookmaker_trees_are_not_imported_by_new_kenyan_store():
    store = (ROOT / "kenyan" / "opportunity_store.py").read_text(encoding="utf-8")
    snapshot = (ROOT / "kenyan" / "match_snapshot.py").read_text(encoding="utf-8")
    combined = store + snapshot
    for banned in (
        "betkanyon",
        "onwin",
        "orbit",
        "kolay90",
        "betfair",
        "verigood",
        "back_lay",
    ):
        assert banned not in combined.lower()


def test_shared_stake_calculator_is_still_back_back_equal_payout():
    source = (ROOT / "engine" / "stake_calculator.py").read_text(encoding="utf-8")
    assert "target_return = bankroll / implied_probability" in source
    assert "home_stake = target_return / best.home_odds" in source
