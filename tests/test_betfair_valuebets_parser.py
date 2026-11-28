"""Betfair valuebets parser tests. Uses fixtures only — no live HTTP."""
import json
from pathlib import Path

from betfair.models import LIVE, PREMATCH, UNKNOWN
from betfair.parser import classify_is_live, parse_payload, parse_record
from betfair.serialize import serialize_opportunity

FIXTURE = Path(__file__).parent / "fixtures" / "betfair_valuebets_sample.json"


def _sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_fixture_list_and_classifies_live_vs_prematch():
    parsed = parse_payload(_sample())
    assert parsed.ok
    assert parsed.rejected == 0
    assert parsed.live_count == 1
    assert parsed.prematch_count == 4
    assert parsed.unknown_count == 0

    by_home = {item.home_team: item for item in parsed.opportunities}
    assert by_home["Wales"].live_classification == PREMATCH
    assert by_home["Wales"].is_live is False
    assert by_home["Germany"].live_classification == PREMATCH
    assert by_home["Chesterfield"].live_classification == PREMATCH
    assert by_home["Queen of South"].line == 2.5
    assert by_home["Queen of South"].outcome == "over"
    assert by_home["Live Alpha"].live_classification == LIVE
    assert by_home["Live Alpha"].is_live is True
    assert by_home["Live Alpha"].live_clock == "67:12"


def test_wrapped_object_payload_is_accepted():
    parsed = parse_payload({"opportunities": _sample()})
    assert parsed.ok
    assert parsed.raw_count == 5


def test_is_live_true_false_and_missing():
    assert classify_is_live(True, present=True) == (True, LIVE)
    assert classify_is_live(False, present=True) == (False, PREMATCH)
    assert classify_is_live(None, present=False) == (None, UNKNOWN)
    assert classify_is_live(None, present=True) == (None, UNKNOWN)
    assert classify_is_live("maybe", present=True) == (None, UNKNOWN)


def test_missing_is_live_is_unknown_not_prematch():
    record = dict(_sample()[0])
    del record["is_live"]
    parsed = parse_record(record)
    assert parsed is not None
    assert parsed.live_classification == UNKNOWN
    assert parsed.is_live is None


def test_malformed_record_does_not_destroy_snapshot():
    payload = [_sample()[0], {"home_team": "Broken"}, _sample()[4]]
    parsed = parse_payload(payload)
    assert parsed.ok
    assert parsed.rejected == 1
    assert len(parsed.opportunities) == 2
    assert parsed.live_count == 1
    assert parsed.prematch_count == 1


def test_duplicate_cluster_id_keeps_one_market():
    first = dict(_sample()[0])
    second = dict(_sample()[0])
    second["value_pct"] = 9.9
    parsed = parse_payload([first, second])
    assert len(parsed.opportunities) == 1
    assert parsed.opportunities[0].value_pct == 9.9


def test_same_match_multiple_markets_are_kept():
    first = dict(_sample()[0])
    second = dict(_sample()[0])
    second["cluster_id"] = first["cluster_id"] + "|other"
    second["outcome"] = "home"
    parsed = parse_payload([first, second])
    assert len(parsed.opportunities) == 2


def test_source_values_are_not_recalculated():
    parsed = parse_record(_sample()[0])
    assert parsed.guaranteed_profit == -6.0
    assert parsed.value_pct == -2.083
    assert parsed.back_stake == 100.0
    serialized = serialize_opportunity(parsed)
    assert serialized["source"] == "betfair"
    assert serialized["opportunityType"] == "BETFAIR"
    assert serialized["isProfitable"] is False
    assert serialized["guaranteedProfit"] == -6.0


def test_timestamps_are_timezone_aware_utc():
    parsed = parse_record(_sample()[0])
    assert parsed.start_time.tzinfo is not None
    assert parsed.start_time.utcoffset().total_seconds() == 0
    assert parsed.start_time.year == 2026
    assert parsed.start_time.month == 10
    assert parsed.start_time.day == 1


def test_unexpected_structure_is_a_parser_error():
    parsed = parse_payload({"detail": "Token gerekli"})
    assert not parsed.ok
    assert parsed.error


def test_optional_null_fields_do_not_reject():
    record = dict(_sample()[0])
    record["line"] = None
    record["live_clock"] = None
    record["refs"] = None
    record["lay_available_size"] = None
    parsed = parse_record(record)
    assert parsed is not None
    assert parsed.line is None
    assert parsed.live_clock is None
