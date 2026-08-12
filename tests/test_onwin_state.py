"""
Deterministic tests for the OnWin persistent state/merge behavior.

Two kinds of coverage:

1. Synthetic-fixture tests (`make_payload` below) that exercise exact
   merge/absence/staleness rules against small, hand-built payloads
   matching OnWin's real schema. These don't depend on any external
   file and stay fast/stable.

2. Real-evidence tests that replay the actual captured traffic in
   output/onwin_main_line.json and output/onwin_event_snapshots.json,
   skipped gracefully if that evidence isn't present on disk.
"""

import json
from pathlib import Path

import pytest

from engine.arbitrage_detector import ArbitrageDetector
from engine.best_odds_selector import BestOddsSelector
from engine.match_finder import MatchFinder
from models.match import MatchOdds
from parsers.onwin.feed import OnwinFeed
from parsers.onwin.parser import FOOTBALL_SPORT_ID
from parsers.onwin.state import OnwinState


REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_LINE_FILE = REPO_ROOT / "output" / "onwin_main_line.json"
EVENT_SNAPSHOTS_FILE = REPO_ROOT / "output" / "onwin_event_snapshots.json"


# ----------------------------------------------------------------------
# Fixture builder
# ----------------------------------------------------------------------

def make_payload(events: dict, versions=None, category_name="Test Country",
                  tournament_name="Test League"):
    """
    Builds a minimal OnWin-shaped payload
    (sports -> categories -> tournaments -> events) containing exactly
    the events passed in, all under the football sport id.
    """

    return {
        "versions": versions if versions is not None else [1],
        "sports": {
            FOOTBALL_SPORT_ID: {
                "categories": {
                    "cat-1": {
                        "diff": {"name": category_name},
                        "tournaments": {
                            "tour-1": {
                                "diff": {"name": tournament_name},
                                "events": events,
                            }
                        },
                    }
                }
            }
        },
        "trace": {},
    }


def make_event(status="in_progress", start_time_ms=1700000000000,
                home="Home FC", away="Away FC",
                home_id="team-home", away_id="team-away",
                odds=None, include_market=True):
    """
    Builds one OnWin event dict. `odds` is an optional
    (p1, draw, p2, updated_at) tuple; when include_market is False the
    scopes/markets tree is omitted entirely (simulating a response that
    doesn't mention this event's market at all).
    """

    event = {
        "diff": {
            "status": status,
            "startTime": start_time_ms,
            "participants": {
                "team1": {"name": home, "shortId": "p1", "teamId": home_id},
                "team2": {"name": away, "shortId": "p2", "teamId": away_id},
            },
            "changeType": "CREATE",
        },
        "scopes": {},
    }

    if include_market:
        if odds is None:
            odds = (1.90, 3.40, 4.10, 1000)

        p1, draw, p2, updated_at = odds

        event["scopes"]["normal_time--0"] = {
            "markets": {
                "score_1x2--nil": {
                    "outcomes": {
                        "outcome::p1": {
                            "coefficient": p1,
                            "updatedAt": updated_at,
                            "changeType": "CREATE",
                        },
                        "outcome::draw": {
                            "coefficient": draw,
                            "updatedAt": updated_at,
                            "changeType": "CREATE",
                        },
                        "outcome::p2": {
                            "coefficient": p2,
                            "updatedAt": updated_at,
                            "changeType": "CREATE",
                        },
                    }
                }
            }
        }

    return event


# ----------------------------------------------------------------------
# 1. Initial state loads correctly / 2. event IDs are preserved
# ----------------------------------------------------------------------

def test_initial_state_loads_correctly():
    state = OnwinState()

    payload = make_payload({
        "evt-1": make_event(),
        "evt-2": make_event(status="not_started", home="Other FC",
                             away="Another FC", include_market=False),
    })

    loaded_ids = state.load_initial(payload)

    assert loaded_ids == {"evt-1", "evt-2"}
    assert state.all_event_ids() == {"evt-1", "evt-2"}
    assert state.event_count == 2
    assert state.last_version == 1
    assert state.initialized is True


# ----------------------------------------------------------------------
# 3. An update changes an existing outcome
# ----------------------------------------------------------------------

def test_update_changes_existing_outcome():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(odds=(2.07, 3.30, 3.60, 1000)),
    }))

    changed = state.apply_update(make_payload(
        {"evt-1": make_event(odds=(2.08, 3.30, 3.55, 2000))},
        versions=[2],
    ))

    assert changed == {"evt-1"}

    [match] = state.get_match_odds(["evt-1"])
    assert match.home_odds == 2.08
    assert match.away_odds == 3.55


# ----------------------------------------------------------------------
# 4. An update containing only one event does not erase other events
# ----------------------------------------------------------------------

def test_update_with_single_event_does_not_erase_others():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(home="Team A", away="Team B"),
        "evt-2": make_event(home="Team C", away="Team D"),
    }))

    changed = state.apply_update(make_payload(
        {"evt-1": make_event(home="Team A", away="Team B",
                              odds=(2.10, 3.30, 3.50, 5000))},
        versions=[2],
    ))

    assert changed == {"evt-1"}
    assert state.all_event_ids() == {"evt-1", "evt-2"}

    odds_by_team = {
        (m.home_team, m.away_team): m for m in state.get_match_odds()
    }
    assert ("Team A", "Team B") in odds_by_team
    assert ("Team C", "Team D") in odds_by_team


# ----------------------------------------------------------------------
# 5. An omitted market does not erase the previous market
# ----------------------------------------------------------------------

def test_omitted_market_does_not_erase_previous_market():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(odds=(1.85, 3.40, 4.20, 1000)),
    }))

    # This update mentions evt-1 (status refresh) but includes no
    # scopes/markets at all for it.
    changed = state.apply_update(make_payload(
        {"evt-1": make_event(include_market=False)},
        versions=[2],
    ))

    # Nothing about the odds changed, so no regeneration is needed.
    assert changed == set()

    [match] = state.get_match_odds(["evt-1"])
    assert match.home_odds == 1.85
    assert match.draw_odds == 3.40
    assert match.away_odds == 4.20


# ----------------------------------------------------------------------
# 6. An omitted outcome does not erase the previous outcome
# ----------------------------------------------------------------------

def test_omitted_outcome_does_not_erase_previous_outcome():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(odds=(1.85, 3.40, 4.20, 1000)),
    }))

    # A market with only two of the three outcomes is treated as an
    # incomplete/absent market by extract_1x2_market -- the existing
    # complete market must be preserved, not partially overwritten.
    partial_event = make_event(odds=(1.85, 3.40, 4.20, 1000))
    del partial_event["scopes"]["normal_time--0"]["markets"]["score_1x2--nil"]["outcomes"]["outcome::p2"]

    changed = state.apply_update(
        make_payload({"evt-1": partial_event}, versions=[2])
    )

    assert changed == set()

    [match] = state.get_match_odds(["evt-1"])
    assert match.away_odds == 4.20


# ----------------------------------------------------------------------
# 7. A new event can be added when it appears
# ----------------------------------------------------------------------

def test_new_event_added_when_it_appears():
    state = OnwinState()
    state.load_initial(make_payload({"evt-1": make_event()}))

    changed = state.apply_update(make_payload(
        {"evt-2": make_event(home="New FC", away="Fresh FC")},
        versions=[2],
    ))

    assert changed == {"evt-2"}
    assert state.all_event_ids() == {"evt-1", "evt-2"}


# ----------------------------------------------------------------------
# 8. Same event with unchanged data produces no unnecessary work
# ----------------------------------------------------------------------

def test_unchanged_event_produces_no_change():
    state = OnwinState()
    payload = make_payload({"evt-1": make_event()})

    state.load_initial(payload)

    # changeType is "CREATE" both times (matching the real feed's
    # observed behavior) -- this must NOT be treated as "new".
    changed = state.apply_update(make_payload(
        {"evt-1": make_event()},
        versions=[2],
    ))

    assert changed == set()


def test_stale_update_does_not_overwrite_newer_value():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(odds=(2.00, 3.30, 3.60, 5000)),
    }))

    # updatedAt (1000) is older than what's already stored (5000) --
    # must be ignored as a stale/out-of-order response.
    changed = state.apply_update(make_payload(
        {"evt-1": make_event(odds=(9.99, 9.99, 9.99, 1000))},
        versions=[2],
    ))

    assert changed == set()

    [match] = state.get_match_odds(["evt-1"])
    assert match.home_odds == 2.00


# ----------------------------------------------------------------------
# 9. MatchOdds generation remains correct
# ----------------------------------------------------------------------

def test_match_odds_generation_correct_fields():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(
            home="Sturm Graz", away="Fenerbahce",
            odds=(2.08, 3.80, 1.84, 1000),
        ),
    }))

    [match] = state.get_match_odds()

    assert isinstance(match, MatchOdds)
    assert match.bookmaker == "OnWin"
    assert match.sport == "football"
    assert match.market == "1X2"
    assert match.home_team == "Sturm Graz"
    assert match.away_team == "Fenerbahce"
    assert match.home_odds == 2.08
    assert match.draw_odds == 3.80
    assert match.away_odds == 1.84


def test_not_started_event_produces_no_match_odds():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(status="not_started"),
    }))

    assert state.get_match_odds() == []


def test_incomplete_market_produces_no_match_odds():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(include_market=False),
    }))

    assert state.get_match_odds() == []


# ----------------------------------------------------------------------
# 10. Existing arbitrage engine still receives valid MatchOdds
# ----------------------------------------------------------------------

def test_arbitrage_engine_accepts_onwin_state_output():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(
            home="Sturm Graz", away="Fenerbahce",
            odds=(2.08, 3.80, 1.84, 1000),
        ),
    }))

    onwin_matches = state.get_match_odds()
    assert len(onwin_matches) == 1

    other_bookmaker = MatchOdds(
        bookmaker="BetKanyon",
        competition="Test League",
        sport="football",
        market="1X2",
        home_team="Sturm Graz",
        away_team="Fenerbahce",
        home_odds=2.20,
        draw_odds=3.50,
        away_odds=1.90,
        start_time=onwin_matches[0].start_time,
        collected_at=onwin_matches[0].collected_at,
    )

    finder = MatchFinder()
    matched_events = finder.find(onwin_matches + [other_bookmaker])

    assert len(matched_events) == 1
    assert len(matched_events[0].matches) == 2

    best = BestOddsSelector().select(matched_events[0])
    result = ArbitrageDetector().detect(best)

    # Not asserting arbitrage_exists (these numbers aren't crafted to
    # necessarily produce one) -- just that the existing engine runs
    # end-to-end on OnwinState-derived MatchOdds without error.
    assert result.best_odds.home_odds == 2.20  # BetKanyon had the better price
    assert result.best_odds.away_odds == 1.90


# ----------------------------------------------------------------------
# 12. Multiple update responses processed sequentially (synthetic)
# ----------------------------------------------------------------------

def test_sequential_updates_apply_in_order():
    state = OnwinState()
    state.load_initial(make_payload({
        "evt-1": make_event(odds=(2.00, 3.30, 3.60, 1000)),
    }))

    versions_seen = [state.last_version]

    for version, odds in [
        (2, (2.02, 3.30, 3.55, 2000)),
        (3, (2.05, 3.25, 3.50, 3000)),
        (4, (2.05, 3.25, 3.50, 3000)),  # repeat -> no-op
    ]:
        state.apply_update(make_payload(
            {"evt-1": make_event(odds=odds)},
            versions=[version],
        ))
        versions_seen.append(state.last_version)

    assert versions_seen == [1, 2, 3, 4]

    [match] = state.get_match_odds(["evt-1"])
    assert match.home_odds == 2.05
    assert match.away_odds == 3.50


# ----------------------------------------------------------------------
# 11. Browser remains alive while updates arrive -- exercised via a
# fake Playwright page (no real browser/network involved).
# ----------------------------------------------------------------------

class _FakePage:
    def __init__(self):
        self.closed = False
        self.ticks = 0

    def is_closed(self):
        return self.closed

    def wait_for_timeout(self, _ms):
        self.ticks += 1


def test_feed_poll_keeps_ticking_while_page_alive():
    feed = OnwinFeed()
    fake_page = _FakePage()
    feed._page = fake_page

    assert feed.is_alive() is True

    for _ in range(5):
        feed.poll(tick_ms=10)

    assert fake_page.ticks == 5

    fake_page.closed = True
    assert feed.is_alive() is False


def test_feed_poll_raises_when_no_page():
    feed = OnwinFeed()

    with pytest.raises(RuntimeError):
        feed.poll()


# ----------------------------------------------------------------------
# Real-evidence tests (skipped gracefully if the captured files aren't
# present on disk).
# ----------------------------------------------------------------------

requires_main_line = pytest.mark.skipif(
    not MAIN_LINE_FILE.exists(),
    reason=f"{MAIN_LINE_FILE} not present (captured evidence file)",
)

requires_event_snapshots = pytest.mark.skipif(
    not EVENT_SNAPSHOTS_FILE.exists(),
    reason=f"{EVENT_SNAPSHOTS_FILE} not present (captured evidence file)",
)


@requires_main_line
def test_real_main_line_snapshot_loads():
    with open(MAIN_LINE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)

    state = OnwinState()
    loaded_ids = state.load_initial(raw)

    assert len(loaded_ids) > 0
    assert state.event_count == len(loaded_ids)

    # Every tracked event must have carried usable participant info
    # (extract_event_diff already enforces this).
    for event_id in loaded_ids:
        ev = state.get_event(event_id)
        assert ev.home_team
        assert ev.away_team


@requires_event_snapshots
def test_real_event_snapshots_sequence_applies_without_error():
    with open(EVENT_SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
        responses = json.load(f)

    assert len(responses) >= 2

    state = OnwinState()
    state.load_initial(responses[0])

    initial_ids = state.all_event_ids()
    assert len(initial_ids) > 0

    for response in responses[1:]:
        # Must never raise, regardless of how many/which events a
        # given response contains.
        state.apply_update(response)

    # Per the forensic analysis, no event present in an earlier
    # response ever vanishes from state just because a later response
    # didn't mention it.
    assert initial_ids.issubset(state.all_event_ids())


@requires_main_line
@requires_event_snapshots
def test_real_event_ids_shared_between_main_line_and_snapshots():
    with open(MAIN_LINE_FILE, "r", encoding="utf-8") as f:
        main_line = json.load(f)

    with open(EVENT_SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
        responses = json.load(f)

    main_state = OnwinState()
    main_state.load_initial(main_line)

    snapshot_state = OnwinState()
    for response in responses:
        snapshot_state.apply_update(response)

    shared_ids = main_state.all_event_ids() & snapshot_state.all_event_ids()

    # This is the ID-stability finding from the forensic analysis: the
    # two feeds share the same event ID space for football events that
    # appear in both captures.
    assert len(shared_ids) > 0
