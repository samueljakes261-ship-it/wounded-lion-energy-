"""Kenyan opportunity identity, odds-update, grace retention, and expiry."""
from datetime import datetime, timezone

from kenyan.api_router import serialize_opportunities
from kenyan.config import BETIKA, SPORTPESA
from kenyan.engine import KenyanArbitrageEngine
from kenyan.models import KenyanMatchOdds
from kenyan.opportunity_store import KenyanOpportunityStore, opportunity_identity


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _match(bookmaker, home_odds, draw_odds, away_odds, *, status="LIVE", event_id="1"):
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="Football",
        market="1X2",
        home_team="Match A Home",
        away_team="Match A Away",
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
        event_id=event_id,
        status=status,
    )


def _compute(home_odds=2.10, status="LIVE"):
    # SportPesa HOME is the best home price; Betika supplies higher
    # draw/away so implied probability is < 1 (2.10/3.30/3.40 alone
    # is not an arbitrage).
    matches = [
        _match(SPORTPESA, home_odds, 3.30, 3.40, status=status, event_id="sp-a"),
        _match(BETIKA, 2.00, 3.90, 4.00, status=status, event_id="bk-a"),
    ]
    return KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)


def test_poll_sequence_create_keep_update_retain_expire():
    store = KenyanOpportunityStore(retention_seconds=45)

    poll_1 = store.apply(_compute(2.10), now=1_000.0)
    assert len(poll_1) == 1
    first = poll_1[0]
    assert first.opportunity.result.best_odds.home_odds == 2.10
    assert first.created_at == 1_000.0
    assert first.updated_at == 1_000.0
    assert first.is_live is True

    poll_2 = store.apply(_compute(2.10), now=1_005.0)
    assert len(poll_2) == 1
    assert poll_2[0].identity == first.identity
    assert poll_2[0].created_at == 1_000.0
    assert poll_2[0].updated_at == 1_000.0
    assert poll_2[0].last_seen_at == 1_005.0

    poll_3 = store.apply(_compute(2.20), now=1_010.0)
    assert len(poll_3) == 1
    assert poll_3[0].identity == first.identity
    assert poll_3[0].opportunity.result.best_odds.home_odds == 2.20
    assert poll_3[0].created_at == 1_000.0
    assert poll_3[0].updated_at == 1_010.0

    poll_4 = store.apply([], now=1_015.0)
    assert len(poll_4) == 1
    assert poll_4[0].identity == first.identity
    assert poll_4[0].opportunity.result.best_odds.home_odds == 2.20

    expired = store.apply([], now=1_015.0 + 46)
    assert expired == []


def test_live_and_prematch_identities_stay_separate():
    store_live = KenyanOpportunityStore(retention_seconds=45)
    store_pre = KenyanOpportunityStore(retention_seconds=45)

    live = store_live.apply(_compute(2.10, status="LIVE"), now=1_000.0)
    pre = store_pre.apply(_compute(2.10, status="PREMATCH"), now=1_000.0)
    assert len(live) == 1
    assert len(pre) == 1
    assert live[0].identity != pre[0].identity
    assert live[0].is_live is True
    assert pre[0].is_live is False
    assert opportunity_identity(live[0].opportunity).startswith("live|")
    assert opportunity_identity(pre[0].opportunity).startswith("prematch|")

    store_live.apply([], now=1_001.0)
    assert len(store_pre.apply(_compute(2.10, status="PREMATCH"), now=1_001.0)) == 1
    assert store_live.apply([], now=1_001.0)[0].is_live is True


def test_serialize_includes_back_back_stake_plan():
    tracked = KenyanOpportunityStore(retention_seconds=45).apply(_compute(2.10), now=1_000.0)
    payload = serialize_opportunities(tracked)
    assert len(payload) == 1
    row = payload[0]
    assert row["opportunityId"] == tracked[0].identity
    assert row["opportunityType"] == "BACK_BACK"
    assert row["isLive"] is True
    assert row["home"]["bookmaker"] == SPORTPESA
    assert row["home"]["odds"] == 2.10
    assert row["home"]["stake"] > 0
    assert row["draw"]["stake"] > 0
    assert row["away"]["stake"] > 0
    assert row["totalStake"] == 1000
    assert row["guaranteedProfit"] > 0
    implied = (
        1 / row["home"]["odds"] + 1 / row["draw"]["odds"] + 1 / row["away"]["odds"]
    )
    assert implied < 1
