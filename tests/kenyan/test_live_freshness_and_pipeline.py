"""LIVE freshness, opportunity lifecycle, and PREMATCH completeness."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from kenyan.api_router import serialize_opportunities
from kenyan.config import (
    BETIKA,
    KENYAN_BETIKA_MAX_PAGES,
    KENYAN_LIVE_STALE_AFTER_SECONDS,
    KENYAN_PREMATCH_STALE_AFTER_SECONDS,
    KENYAN_VZIP_MAX_PAGES,
    ONEXBET,
    SPORTPESA,
)
from kenyan.engine import KenyanArbitrageEngine
from kenyan.http_utils import FetchResult
from kenyan.match_snapshot import merge_match_records, visible_matches
from kenyan.models import KenyanMatchOdds
from kenyan.opportunity_store import KenyanOpportunityStore, opportunity_identity
from kenyan.runner import KenyanEngineRunner
from kenyan.workers.base import BaseKenyanWorker, Diagnostics
from kenyan.workers.vzip_pages import fetch_vzip_all
from kenyan.workers import sportpesa


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _ok(url, body, *, bytes_len=64):
    return FetchResult(
        url=url,
        ok=True,
        status_code=200,
        content_type="application/json",
        response_size_bytes=bytes_len,
        elapsed_seconds=0.01,
        json_body=body,
    )


def _match(
    bookmaker,
    home_odds,
    draw_odds,
    away_odds,
    *,
    status="LIVE",
    event_id="1",
    sport="Football",
    market="1X2",
    line=None,
    period="FULL_MATCH",
    collected_at=NOW,
    home="Alpha",
    away="Beta",
):
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport=sport,
        market=market,
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=collected_at,
        event_id=event_id,
        status=status,
        line=line,
        period=period,
    )


def _arb_pair(status="LIVE", home_odds=2.10):
    return [
        _match(SPORTPESA, home_odds, 3.30, 3.40, status=status, event_id="sp-a"),
        _match(BETIKA, 2.00, 3.90, 4.00, status=status, event_id="bk-a"),
    ]


def _compute(status="LIVE", home_odds=2.10, now=NOW):
    return KenyanArbitrageEngine().compute_opportunities(
        _arb_pair(status=status, home_odds=home_odds),
        bankroll=1000,
        now=now,
    )


def test_new_opportunity_appears_and_identical_poll_keeps_identity():
    store = KenyanOpportunityStore(retention_seconds=45)
    first = store.apply(_compute(), now=1_000.0)
    assert len(first) == 1
    second = store.apply(_compute(), now=1_005.0)
    assert len(second) == 1
    assert second[0].identity == first[0].identity
    assert second[0].created_at == 1_000.0
    assert second[0].updated_at == 1_000.0


def test_odds_change_updates_same_logical_opportunity():
    store = KenyanOpportunityStore(retention_seconds=45)
    first = store.apply(_compute(home_odds=2.10), now=1_000.0)[0]
    updated = store.apply(_compute(home_odds=2.20), now=1_010.0)[0]
    assert updated.identity == first.identity
    assert updated.opportunity.result.best_odds.home_odds == 2.20
    assert updated.updated_at == 1_010.0


def test_out_of_order_merge_cannot_overwrite_newer_odds():
    newer = _match(SPORTPESA, 2.20, 3.30, 3.40, event_id="1")
    older = _match(SPORTPESA, 2.10, 3.30, 3.40, event_id="1")
    records = merge_match_records({}, [newer], now=100.0, retention_seconds=45, acquired_seq=5)
    records = merge_match_records(records, [older], now=110.0, retention_seconds=45, acquired_seq=4)
    visible = visible_matches(records, now=110.0, retention_seconds=45)
    assert visible[0].home_odds == 2.20


def test_temporary_missing_record_is_retained_then_expires():
    store = KenyanOpportunityStore(retention_seconds=45)
    store.apply(_compute(), now=1_000.0)
    retained = store.apply([], now=1_020.0)
    assert len(retained) == 1
    assert store.apply([], now=1_046.0) == []


def test_quiet_live_price_is_not_stale_when_recently_confirmed():
    aged = NOW - timedelta(seconds=120)
    quiet = _match(SPORTPESA, 2.10, 3.30, 3.40, collected_at=aged)
    quiet.confirmed_at = NOW
    partner = _match(BETIKA, 2.00, 3.90, 4.00, event_id="2")
    partner.confirmed_at = NOW
    found = KenyanArbitrageEngine().compute_opportunities([quiet, partner], now=NOW)
    assert len(found) == 1


def test_unconfirmed_live_constituent_is_rejected():
    stale_confirm = NOW - timedelta(seconds=KENYAN_LIVE_STALE_AFTER_SECONDS + 1)
    quiet = _match(SPORTPESA, 2.10, 3.30, 3.40, collected_at=NOW)
    quiet.confirmed_at = stale_confirm
    partner = _match(BETIKA, 2.00, 3.90, 4.00, event_id="2")
    partner.confirmed_at = NOW
    assert KenyanArbitrageEngine().compute_opportunities([quiet, partner], now=NOW) == []


def test_stale_live_odds_are_rejected_inside_live_window():
    stale = _match(
        SPORTPESA,
        2.10,
        3.30,
        3.40,
        collected_at=NOW - timedelta(seconds=KENYAN_LIVE_STALE_AFTER_SECONDS + 1),
    )
    fresh = _match(BETIKA, 2.00, 3.90, 4.00, event_id="2")
    assert KenyanArbitrageEngine().compute_opportunities([stale, fresh], now=NOW) == []


def test_prematch_uses_longer_stale_window_than_live():
    assert KENYAN_PREMATCH_STALE_AFTER_SECONDS > KENYAN_LIVE_STALE_AFTER_SECONDS
    aged = NOW - timedelta(seconds=60)
    live = _arb_pair(status="LIVE")
    live[0].collected_at = aged
    live[1].collected_at = aged
    assert KenyanArbitrageEngine().compute_opportunities(live, now=NOW) == []

    pre = _arb_pair(status="PREMATCH")
    pre[0].collected_at = aged
    pre[1].collected_at = aged
    assert KenyanArbitrageEngine().compute_opportunities(pre, now=NOW)


def test_successful_empty_poll_keeps_last_valid_until_retention():
    state = {"empty": False}

    def poll_fn():
        if state["empty"]:
            return [], Diagnostics(endpoint_status="ok", valid_normalized_events=0)
        return _arb_pair()[:1], Diagnostics(endpoint_status="ok", valid_normalized_events=1)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=100, retention_seconds=45)
    worker._run_one_cycle()
    assert len(worker.get_matches()) == 1
    state["empty"] = True
    worker._run_one_cycle()
    assert len(worker.get_matches()) == 1


def test_failed_poll_does_not_wipe_last_valid_snapshot():
    state = {"fail": False}

    def poll_fn():
        if state["fail"]:
            return [], Diagnostics(endpoint_status="http_error", parser_error="HTTP 500")
        return _arb_pair()[:1], Diagnostics(endpoint_status="ok", valid_normalized_events=1)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=100)
    worker._run_one_cycle()
    assert len(worker.get_matches()) == 1
    collected = worker.get_matches()[0].collected_at
    state["fail"] = True
    worker._run_one_cycle()
    remaining = worker.get_matches()
    assert len(remaining) == 1
    assert remaining[0].collected_at == collected


def test_get_matches_does_not_restamp_collected_at():
    def poll_fn():
        return [_match(SPORTPESA, 2.1, 3.3, 3.4)], Diagnostics(
            endpoint_status="ok", valid_normalized_events=1
        )

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=100)
    worker._run_one_cycle()
    first = worker.get_matches()[0].collected_at
    second = worker.get_matches()[0].collected_at
    assert first == second


def test_live_and_prematch_identities_and_stores_stay_separate():
    live = _compute(status="LIVE")[0]
    pre = _compute(status="PREMATCH")[0]
    assert opportunity_identity(live).startswith("live|")
    assert opportunity_identity(pre).startswith("prematch|")
    assert opportunity_identity(live) != opportunity_identity(pre)


def test_runner_compute_loops_are_independent():
    runner = KenyanEngineRunner()
    assert runner._live_compute_thread is None
    assert runner._prematch_compute_thread is None
    assert runner._live_store._retention_seconds == KENYAN_LIVE_STALE_AFTER_SECONDS
    assert runner._prematch_store._retention_seconds == KENYAN_PREMATCH_STALE_AFTER_SECONDS


def test_vzip_walks_more_than_former_40_page_cap():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        start = 1 if after is None else int(after) + 1
        events = [{"I": index} for index in range(start, start + 50)]
        return _ok(url, {"Value": events})

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=50,
        max_pages=45,
    )
    assert len(envelope["Value"]) == 45 * 50
    assert result.page_cap_hit is True
    assert result.snapshot_complete is False
    assert result.pages_fetched == 45
    assert KENYAN_VZIP_MAX_PAGES > 40
    assert KENYAN_BETIKA_MAX_PAGES > 40


def test_vzip_incomplete_later_page_keeps_earlier_events():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        after = parse_qs(urlsplit(url).query).get("after", [None])[0]
        if after is None:
            return _ok(url, {"Value": [{"I": 1}, {"I": 2}, {"I": 3}]})
        return FetchResult(
            url=url,
            ok=False,
            status_code=500,
            content_type="application/json",
            response_size_bytes=0,
            elapsed_seconds=0.01,
            error="HTTP 500",
        )

    envelope, result = fetch_vzip_all(
        "https://example.test/Get1x2_VZip?sports=1",
        fetch=fake_fetch,
        page_count=3,
    )
    assert [event["I"] for event in envelope["Value"]] == [1, 2, 3]
    assert result.snapshot_complete is False


def test_sportpesa_live_discovery_pages_until_short_page(monkeypatch):
    calls = []

    def fake_fetch(url, headers=None):
        calls.append(url)
        if "/live/sports/" in url:
            query = parse_qs(urlsplit(url).query)
            offset = int(query.get("offset", ["0"])[0])
            if offset == 0:
                events = [
                    {
                        "id": index,
                        "sport": {"id": 1},
                        "competitors": [{"id": index, "name": f"H{index}"}, {"id": index + 100, "name": f"A{index}"}],
                        "tournament": {"name": "L", "id": 1},
                    }
                    for index in range(1, 51)
                ]
                return _ok(url, {"events": events})
            return _ok(
                url,
                {
                    "events": [
                        {
                            "id": 51,
                            "sport": {"id": 1},
                            "competitors": [{"id": 51, "name": "H51"}, {"id": 151, "name": "A51"}],
                            "tournament": {"name": "L", "id": 1},
                        }
                    ]
                },
            )
        return _ok(url, {"markets": []})

    monkeypatch.setattr(sportpesa, "fetch_json", fake_fetch)
    matches, diagnostics = sportpesa._poll_live()
    assert diagnostics.pages_fetched >= 3
    assert diagnostics.events_discovered == 51
    assert any("offset=50" in url for url in calls)
    assert matches == []


def test_different_total_lines_and_periods_never_share_identity():
    line_a = _match(
        SPORTPESA, 2.1, None, 1.8, market="TOTAL", line=2.5, period="FULL_MATCH", event_id="1"
    )
    line_b = _match(
        SPORTPESA, 2.2, None, 1.7, market="TOTAL", line=3.5, period="FULL_MATCH", event_id="1"
    )
    period_b = _match(
        SPORTPESA, 2.1, None, 1.8, market="TOTAL", line=2.5, period="1ST_HALF", event_id="1"
    )
    records = merge_match_records({}, [line_a, line_b, period_b], now=1.0, retention_seconds=45)
    assert len(records) == 3


def test_two_way_tennis_does_not_acquire_a_draw():
    matches = [
        KenyanMatchOdds(
            bookmaker=ONEXBET,
            competition="ATP",
            sport="Tennis",
            market="Match Winner",
            home_team="Player A",
            away_team="Player B",
            home_odds=1.90,
            draw_odds=None,
            away_odds=2.10,
            start_time=NOW,
            collected_at=NOW,
            event_id="t1",
            status="PREMATCH",
            market_type="MATCH_WINNER",
            period="FULL_MATCH",
        ),
        KenyanMatchOdds(
            bookmaker=BETIKA,
            competition="ATP",
            sport="Tennis",
            market="Match Winner",
            home_team="Player A",
            away_team="Player B",
            home_odds=2.20,
            draw_odds=None,
            away_odds=1.80,
            start_time=NOW,
            collected_at=NOW,
            event_id="t2",
            status="PREMATCH",
            market_type="MATCH_WINNER",
            period="FULL_MATCH",
        ),
    ]
    opportunities = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)
    assert len(opportunities) == 1
    payload = serialize_opportunities(opportunities)
    assert payload[0]["outcomeCount"] == 2
    assert payload[0]["draw"] is None
    assert payload[0]["home"]["odds"] == 2.20
    assert payload[0]["away"]["odds"] == 2.10


def test_non_arbitrage_is_rejected_and_invalid_odds_are_measurable():
    even = [
        _match(SPORTPESA, 2.00, 3.20, 3.80, status="PREMATCH", event_id="a"),
        _match(BETIKA, 2.00, 3.20, 3.80, status="PREMATCH", event_id="b"),
    ]
    assert KenyanArbitrageEngine().compute_opportunities(even, now=NOW) == []
    invalid = [_match(SPORTPESA, 0, 0, 0, status="PREMATCH")]
    assert KenyanArbitrageEngine().compute_opportunities(invalid, now=NOW) == []


def test_one_malformed_market_does_not_drop_a_valid_arb():
    good = _arb_pair(status="PREMATCH")
    bad = _match(ONEXBET, 0, 0, 0, status="PREMATCH", event_id="bad", home="Other", away="Side")
    opportunities = KenyanArbitrageEngine().compute_opportunities(good + [bad], now=NOW)
    assert len(opportunities) == 1
    payload = serialize_opportunities(opportunities)
    assert payload[0]["opportunityId"]
    assert payload[0]["lastUpdated"] or payload[0]["collectedAt"]


def test_deduplication_does_not_collapse_different_lines():
    store = KenyanOpportunityStore(retention_seconds=180)
    first = KenyanArbitrageEngine().compute_opportunities(
        [
            KenyanMatchOdds(
                bookmaker=ONEXBET,
                competition="X",
                sport="Football",
                market="TOTAL",
                home_team="Alpha",
                away_team="Beta",
                home_odds=2.10,
                draw_odds=None,
                away_odds=1.90,
                start_time=NOW,
                collected_at=NOW,
                event_id="1x-a",
                status="PREMATCH",
                line=2.5,
                period="FULL_MATCH",
                market_type="TOTAL",
            ),
            KenyanMatchOdds(
                bookmaker=BETIKA,
                competition="X",
                sport="Football",
                market="TOTAL",
                home_team="Alpha",
                away_team="Beta",
                home_odds=1.80,
                draw_odds=None,
                away_odds=2.20,
                start_time=NOW,
                collected_at=NOW,
                event_id="bk-a",
                status="PREMATCH",
                line=2.5,
                period="FULL_MATCH",
                market_type="TOTAL",
            ),
        ],
        now=NOW,
    )
    second = KenyanArbitrageEngine().compute_opportunities(
        [
            KenyanMatchOdds(
                bookmaker=ONEXBET,
                competition="X",
                sport="Football",
                market="TOTAL",
                home_team="Alpha",
                away_team="Beta",
                home_odds=2.10,
                draw_odds=None,
                away_odds=1.90,
                start_time=NOW,
                collected_at=NOW,
                event_id="1x-b",
                status="PREMATCH",
                line=3.5,
                period="FULL_MATCH",
                market_type="TOTAL",
            ),
            KenyanMatchOdds(
                bookmaker=BETIKA,
                competition="X",
                sport="Football",
                market="TOTAL",
                home_team="Alpha",
                away_team="Beta",
                home_odds=1.80,
                draw_odds=None,
                away_odds=2.20,
                start_time=NOW,
                collected_at=NOW,
                event_id="bk-b",
                status="PREMATCH",
                line=3.5,
                period="FULL_MATCH",
                market_type="TOTAL",
            ),
        ],
        now=NOW,
    )
    tracked = store.apply(first + second, now=1_000.0)
    assert len(tracked) == 2
    assert tracked[0].identity != tracked[1].identity
