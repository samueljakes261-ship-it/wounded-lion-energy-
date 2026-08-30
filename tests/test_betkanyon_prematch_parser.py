from datetime import datetime, timezone

from parsers.betkanyon.parser import parse_json as parse_live
from parsers.betkanyon_prematch.adapter import BetkanyonPrematchAdapter
from parsers.betkanyon_prematch.parser import parse_prematch


def _stake(sn, price, locked=False, active=True, extra=None):
    row = {
        "Id": 9001,
        "N": str(sn),
        "SN": sn,
        "F": price,
        "IsL": locked,
        "IsA": active,
    }
    if extra:
        row.update(extra)
    return row


def _market(stakes, market_id=1, name="Maç Sonucu"):
    return {"Id": market_id, "N": name, "Stakes": stakes}


def _event(home, away, markets, event_id=1001, kickoff="2026-08-21T12:00:00Z"):
    return {
        "Id": event_id,
        "EHT": home,
        "HT": home,
        "EAT": away,
        "AT": away,
        "D": kickoff,
        "ECN": "Test League",
        "CN": "Test League",
        "ESN": "Football",
        "StakeTypes": markets,
    }


def _payload(*events):
    return {
        "N": "Football",
        "EGN": "Football",
        "CNT": [
            {
                "N": "Testland",
                "CL": [{"N": "Test League", "EGN": "Test League", "E": list(events)}],
            }
        ],
    }


def test_valid_prematch_event_produces_one_match_odds():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        _stake("1", 2.10),
                        _stake("X", 3.40),
                        _stake("2", 3.10),
                    ]
                )
            ],
        )
    )
    parsed, stats = parse_prematch(payload)
    assert stats["events_discovered"] == 1
    assert len(parsed) == 1


def test_valid_1x2_market_maps_home_draw_away():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        _stake("Kazanan2", 3.10),
                        _stake("X", 3.40),
                        _stake("1", 2.10),
                    ]
                )
            ],
        )
    )
    parsed, _stats = parse_prematch(payload)
    event = parsed[0]
    assert event["home"] == "Alpha FC"
    assert event["away"] == "Beta FC"
    assert event["home_odds"] == 2.10
    assert event["draw_odds"] == 3.40
    assert event["away_odds"] == 3.10


def test_feed_type_is_prematch():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [_market([_stake("1", 2.1), _stake("X", 3.4), _stake("2", 3.1)])],
        )
    )
    parsed, _stats = parse_prematch(payload)
    match = BetkanyonPrematchAdapter.to_match_odds(parsed[0], tournament_id="4520")
    assert match.feed_type == "prematch"


def test_tournament_id_is_preserved():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [_market([_stake("1", 2.1), _stake("X", 3.4), _stake("2", 3.1)])],
        )
    )
    parsed, _stats = parse_prematch(payload)
    match = BetkanyonPrematchAdapter.to_match_odds(parsed[0], tournament_id="4520")
    assert match.tournament_id == "4520"


def test_non_1x2_markets_are_ignored():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [_stake("Üst", 1.85), _stake("Alt", 1.95)],
                    market_id=702,
                    name="Toplam Gol",
                )
            ],
        )
    )
    parsed, stats = parse_prematch(payload)
    assert stats["events_discovered"] == 1
    assert parsed == []
    assert stats["complete_1x2"] == 0


def test_bogus_numeric_ids_are_not_odds():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        _stake("1", 4520),
                        _stake("X", 313639),
                        _stake("2", 2533),
                    ]
                )
            ],
        )
    )
    parsed, stats = parse_prematch(payload)
    assert parsed == []
    assert stats["complete_1x2"] == 0


def test_multiple_events_in_one_payload():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [_market([_stake("1", 2.1), _stake("X", 3.4), _stake("2", 3.1)])],
            event_id=1,
        ),
        _event(
            "Gamma FC",
            "Delta FC",
            [_market([_stake("1", 1.70), _stake("X", 3.60), _stake("2", 5.10)])],
            event_id=2,
        ),
    )
    parsed, stats = parse_prematch(payload)
    assert stats["events_discovered"] == 2
    assert len(parsed) == 2
    names = {(row["home"], row["away"]) for row in parsed}
    assert names == {("Alpha FC", "Beta FC"), ("Gamma FC", "Delta FC")}


def test_locked_or_missing_selections_do_not_emit_complete_1x2():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        _stake("1", 2.10),
                        _stake("X", None, locked=True),
                        _stake("2", None),
                    ]
                )
            ],
        )
    )
    parsed, stats = parse_prematch(payload)
    assert parsed == []
    assert stats["events_discovered"] == 1
    assert stats["complete_1x2"] == 0


def test_locked_selection_with_valid_price_is_still_used():
    # Live BetKanyon 1X2 rows are often IsL=true while F is still a
    # real decimal price. Missing F is the lock that must drop the market.
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        _stake("1", 2.10, locked=True),
                        _stake("X", 3.40, locked=True),
                        _stake("2", 3.10, locked=True),
                    ]
                )
            ],
        )
    )
    parsed, _stats = parse_prematch(payload)
    assert len(parsed) == 1
    assert parsed[0]["home_odds"] == 2.10


def test_list_root_payload_is_walked():
    payload = [
        _payload(
            _event(
                "Alpha FC",
                "Beta FC",
                [_market([_stake("1", 2.1), _stake("X", 3.4), _stake("2", 3.1)])],
            )
        )
    ]
    parsed, stats = parse_prematch(payload)
    assert stats["events_discovered"] == 1
    assert len(parsed) == 1


def test_selection_codes_map_home_draw_away_without_sn():
    payload = _payload(
        _event(
            "Alpha FC",
            "Beta FC",
            [
                _market(
                    [
                        {"SC": 1, "F": 2.10, "IsL": False, "IsA": True},
                        {"SC": 2, "F": 3.40, "IsL": False, "IsA": True},
                        {"SC": 3, "F": 3.10, "IsL": False, "IsA": True},
                    ]
                )
            ],
        )
    )
    assert parse_live(payload) == []
    parsed, _stats = parse_prematch(payload)
    assert len(parsed) == 1
    assert parsed[0]["home_odds"] == 2.10
    assert parsed[0]["draw_odds"] == 3.40
    assert parsed[0]["away_odds"] == 3.10


def test_prematch_schema_variants_live_parser_misses():
    # Live parser requires CNT/CL/E, Id == 1 (int), and SN as strings
    # "1"/"X"/"2". Prematch payloads have been observed to vary.
    payload = {
        "Sports": [
            {
                "Events": [
                    {
                        "Id": 77,
                        "EHT": "Alpha FC",
                        "EAT": "Beta FC",
                        "D": "2026-08-21T12:00:00Z",
                        "stakeTypes": [
                            {
                                "Id": "1",
                                "N": "Match Odds",
                                "Stakes": [
                                    {"SN": 1, "F": "2.10"},
                                    {"SN": "X", "F": 3.40},
                                    {"SN": 2, "F": 3.10},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    assert parse_live(payload) == []
    parsed, stats = parse_prematch(payload)
    assert stats["events_discovered"] == 1
    assert len(parsed) == 1
    assert parsed[0]["home_odds"] == 2.10
    match = BetkanyonPrematchAdapter.to_match_odds(parsed[0], tournament_id="4520")
    assert match.feed_type == "prematch"
    assert match.start_time == datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
