"""Compare two Onwin 1X2 parses. Does not start a browser or ZenRows."""

from __future__ import annotations


def _key(match) -> tuple[str, str]:
    return (match.home_team, match.away_team)


def compare_matches(experiment, production) -> dict:
    experiment_map = {_key(match): match for match in experiment}
    production_map = {_key(match): match for match in production}
    shared = sorted(set(experiment_map) & set(production_map))
    odds_mismatch = 0
    for key in shared:
        left = experiment_map[key]
        right = production_map[key]
        if (left.home_odds, left.draw_odds, left.away_odds) != (
            right.home_odds,
            right.draw_odds,
            right.away_odds,
        ):
            odds_mismatch += 1
    return {
        "experiment_rows": len(experiment_map),
        "production_rows": len(production_map),
        "shared_events": len(shared),
        "only_experiment": len(set(experiment_map) - set(production_map)),
        "only_production": len(set(production_map) - set(experiment_map)),
        "odds_mismatch": odds_mismatch,
    }
