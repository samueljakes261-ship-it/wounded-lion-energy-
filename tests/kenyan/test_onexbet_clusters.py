from kenyan.parsers._common_1x2 import (
    extract_1x2_clusters_from_event_groups,
    extract_1x2_from_event_groups,
    extract_1x2_from_flat_events,
)
from kenyan.parsers.onexbet_parser import parse_events


def _grouped_event(home="Chelsea", away="Brighton", clusters=None, **extra):
    if clusters is None:
        clusters = [(1.5, 3.5, 4.5)]
    wrappers = []
    for home_odds, draw_odds, away_odds in clusters:
        wrappers.extend(
            [
                [{"type": 1, "cf": home_odds}],
                [{"type": 2, "cf": draw_odds}],
                [{"type": 3, "cf": away_odds}],
            ]
        )
    event = {
        "sport": {"id": 1, "name": "Football"},
        "opponent1": {"fullName": home, "opps": [{"id": 1988, "name": home}]},
        "opponent2": {"fullName": away, "opps": [{"id": 2026, "name": away}]},
        "liga": {"id": 88637, "name": "England. Premier League"},
        "id": 748537948,
        "mainGameId": 748537948,
        "periodName": "",
        "startTs": 1788094800,
        "eventGroups": [{"groupId": 1, "events": wrappers}],
    }
    event.update(extra)
    return event


def test_same_cluster_home_draw_away_kept_together():
    prices = extract_1x2_from_event_groups(
        _grouped_event()["eventGroups"]
    )
    assert prices == {1: 1.5, 2: 3.5, 3: 4.5}


def test_mixed_sequential_clusters_do_not_overwrite_first_1x2():
    event = _grouped_event(clusters=[(1.5, 3.5, 4.5), (9.0, 8.0, 7.0)])
    clusters = extract_1x2_clusters_from_event_groups(event["eventGroups"])
    assert len(clusters) == 2
    assert clusters[0]["prices"] == {1: 1.5, 2: 3.5, 3: 4.5}
    assert clusters[0]["cluster_id"] == "g1:c0"
    assert clusters[1]["prices"] == {1: 9.0, 2: 8.0, 3: 7.0}

    parsed = parse_events([event], status="LIVE")
    assert len(parsed) == 1
    assert parsed[0].home_odds == 1.5
    assert parsed[0].draw_odds == 3.5
    assert parsed[0].away_odds == 4.5
    assert parsed[0].cluster_id == "g1:c0"
    assert parsed[0].event_id == "748537948"
    assert parsed[0].market_id == "1"


def test_aligned_parallel_clusters_keep_index_zero_only():
    event_groups = [
        {
            "groupId": 1,
            "events": [
                [{"type": 1, "cf": 1.5}, {"type": 1, "cf": 9.0}],
                [{"type": 2, "cf": 3.5}, {"type": 2, "cf": 8.0}],
                [{"type": 3, "cf": 4.5}, {"type": 3, "cf": 7.0}],
            ],
        }
    ]
    clusters = extract_1x2_clusters_from_event_groups(event_groups)
    assert [item["cluster_id"] for item in clusters] == ["g1:c0", "g1:c1"]
    parsed = parse_events(
        [
            _grouped_event()
            | {"eventGroups": event_groups}
        ],
        status="LIVE",
    )
    assert parsed[0].home_odds == 1.5
    assert parsed[0].away_odds == 4.5
    assert parsed[0].cluster_id == "g1:c0"


def test_wrong_market_group_is_ignored():
    event_groups = [
        {
            "groupId": 8,
            "events": [
                [{"type": 1, "cf": 1.01}],
                [{"type": 2, "cf": 2.01}],
                [{"type": 3, "cf": 3.01}],
            ],
        },
        {
            "groupId": 1,
            "events": [
                [{"type": 1, "cf": 2.10}],
                [{"type": 2, "cf": 3.20}],
                [{"type": 3, "cf": 3.40}],
            ],
        },
    ]
    prices = extract_1x2_from_event_groups(event_groups)
    assert prices == {1: 2.10, 2: 3.20, 3: 3.40}


def test_satellite_period_event_is_rejected():
    event = _grouped_event(periodName="1st half", id=111, mainGameId=748537948)
    assert parse_events([event], status="LIVE") == []


def test_satellite_id_not_equal_main_game_id_is_rejected():
    event = _grouped_event(id=999, mainGameId=748537948)
    assert parse_events([event], status="LIVE") == []


def test_flat_mixed_clusters_keep_first_complete_triple():
    events = [
        {"T": 1, "C": 1.4, "G": 1},
        {"T": 2, "C": 3.4, "G": 1},
        {"T": 3, "C": 4.4, "G": 1},
        {"T": 1, "C": 11.0, "G": 1},
        {"T": 2, "C": 12.0, "G": 1},
        {"T": 3, "C": 13.0, "G": 1},
    ]
    assert extract_1x2_from_flat_events(events) == {1: 1.4, 2: 3.4, 3: 4.4}


def test_real_live_fixture_retains_cluster_provenance(fixture_loader):
    payload = fixture_loader("onexbet_live.json")
    matches = parse_events(payload, status="LIVE")
    chelsea = next(m for m in matches if m.home_team == "Chelsea")
    assert chelsea.cluster_id == "g1:c0"
    assert chelsea.market_id == "1"
    assert chelsea.event_id
    assert chelsea.parent_event_id == chelsea.event_id
