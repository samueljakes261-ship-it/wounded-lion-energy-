"""Unit tests for the one-shot PREMATCH diagnostic helpers. No live HTTP."""
from datetime import datetime, timezone

from kenyan.diagnostics.export import (
    classify_betika_event,
    classify_sportpesa_game,
    classify_vzip_event,
    matchodds_record,
    sanitize_url,
)
from kenyan.models import KenyanMatchOdds


def test_sanitize_url_redacts_secrets_keeps_source_ids():
    url = sanitize_url(
        "https://1xbet.co.ke/service-api/LineFeed/Get1x2_VZip?champs=99&count=50&token=secret"
    )
    assert "token=<redacted>" in url
    assert "champs=99" in url
    assert "secret" not in url


def test_matchodds_record_uses_real_fields_and_marks_missing_selection_ids():
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    match = KenyanMatchOdds(
        bookmaker="1xBet",
        competition="MLS",
        sport="Football",
        market="1X2",
        home_team="Home FC",
        away_team="Away FC",
        home_odds=2.1,
        draw_odds=3.2,
        away_odds=3.4,
        start_time=now,
        collected_at=now,
        event_id="123",
        status="PREMATCH",
        source="onexbet_prematch",
    )
    record = matchodds_record(match)
    assert record["source_event_id"] == "123"
    assert record["draw_odds"] == 3.2
    assert record["selection_ids"] is None
    assert "not retained" in record["selection_ids_note"]
    assert record["canonical_event_key"].startswith("football|")


def test_classify_helpers_cover_parser_skip_reasons():
    assert classify_vzip_event({"SI": 99, "O1": "A", "O2": "B", "S": 1, "I": 2}) == "unsupported_sport"
    assert classify_vzip_event({"SI": 1, "O1": "Home", "O2": "Away", "S": 1, "I": 2}) == "placeholder_fixture"
    assert classify_vzip_event({"SI": 1, "O1": "A", "O2": "B", "S": 1, "I": 2}) == "no_supported_market"
    assert classify_betika_event({"sport_name": "hockey", "home_team": "A", "away_team": "B"}) == "unsupported_sport"
    assert classify_sportpesa_game({"sport": {"id": 2}}) == "unsupported_sport"
