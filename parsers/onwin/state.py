"""
Persistent in-memory representation of OnWin's football odds.

Built ONCE from a get_main_line.erisgaming snapshot (load_initial), then
patched incrementally from find_event_snapshots.erisgaming responses
(apply_update) without ever re-walking the ~17 MB initial payload again.

Design rules, derived from the forensic analysis of captured OnWin
traffic (see output/onwin_event_snapshots.json):

- Every response only carries a SUBSET of events. Absence of an event,
  market, or outcome from a response means "no information this cycle",
  never "removed". apply_update() therefore only ever touches entities
  that are actually present in the payload it is given.
- Entities that ARE present carry complete state (never sparse partial
  fields), so a present entity can simply replace the stored one.
- `diff.changeType` has only ever been observed as "CREATE", including
  for byte-identical repeats of previously-seen data. It is therefore
  NOT used as a signal for "this is new" -- presence + a value-level
  comparison against the existing stored state is used instead.
- `updatedAt` is tracked per outcome and used as a safeguard so an
  out-of-order/older update can't clobber a newer known coefficient.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from debug import odds_trace
from models.match import MatchOdds
from parsers.onwin.parser import (
    FOOTBALL_SPORT_ID,
    extract_1x2_market,
    extract_event_diff,
)


@dataclass(frozen=True)
class OnwinEventState:
    """One tracked OnWin event -- enough to rebuild MatchOdds without
    ever needing to re-fetch get_main_line."""

    event_id: str
    competition: str

    status: str | None
    start_time_ms: int | None

    home_team: str
    home_team_id: str | None
    away_team: str
    away_team_id: str | None

    home_odds: float | None = None
    draw_odds: float | None = None
    away_odds: float | None = None

    home_updated_at: int | None = None
    draw_updated_at: int | None = None
    away_updated_at: int | None = None


class OnwinState:
    """
    event_id -> OnwinEventState store for OnWin football events.

    Only football events are retained (matching the existing parser's
    scope) and only the normal_time--0 / score_1x2--nil market is
    tracked (matching the current arbitrage MVP's scope). Non-football
    sports and secondary in-play markets are ignored entirely rather
    than stored and discarded, to keep the state small and cheap to
    patch.
    """

    def __init__(self):
        self._events: dict[str, OnwinEventState] = {}
        self.last_version: int | None = None
        self.initialized = False

        # Diagnostics only (not used for any merge/patch decision):
        # how many events the most recent apply_update() payload
        # actually contained, for terminal status logging.
        self.last_update_event_count: int = 0

    @property
    def event_count(self) -> int:
        return len(self._events)

    def load_initial(self, raw_json: dict) -> set[str]:
        """
        Build local state from a full get_main_line.erisgaming payload.

        This is the ONLY place a full walk of the (large) initial feed
        should happen. Replaces any previously held state entirely.
        """

        events = {}

        self._walk_football(raw_json, events)

        self._events = events
        self.last_version = self._extract_version(raw_json)
        self.initialized = True

        return set(events.keys())

    def apply_update(self, raw_json) -> set[str]:
        """
        Merge a live-update payload into local state.

        Accepts the documented find_event_snapshots object shape
        (`{"sports": ...}`) and the live get_main_line_gap form, which
        arrives as a JSON array of the same objects (or of wrapper
        dicts with a sports/result/data field). A list payload used to
        raise AttributeError and freeze OnWin odds after the snapshot.
        """

        changed: set[str] = set()
        for payload in self._coerce_update_payloads(raw_json):
            changed |= self._apply_one_update(payload)
        return changed

    @staticmethod
    def _coerce_update_payloads(raw_json) -> list[dict]:
        """Unwrap list/result wrappers into dicts that have `sports`."""
        if raw_json is None:
            return []

        if isinstance(raw_json, list):
            payloads: list[dict] = []
            for item in raw_json:
                payloads.extend(OnwinState._coerce_update_payloads(item))
            return payloads

        if not isinstance(raw_json, dict):
            return []

        if "sports" in raw_json:
            return [raw_json]

        for key in ("result", "data", "payload", "diff"):
            inner = raw_json.get(key)
            if isinstance(inner, (dict, list)):
                return OnwinState._coerce_update_payloads(inner)

        return [raw_json]

    def _apply_one_update(self, raw_json: dict) -> set[str]:
        changed: set[str] = set()

        incoming: dict[str, OnwinEventState] = {}
        self._walk_football(raw_json, incoming)

        self.last_update_event_count = len(incoming)

        version = self._extract_version(raw_json)

        if version is not None:
            self.last_version = (
                version
                if self.last_version is None
                else max(self.last_version, version)
            )

        for event_id, candidate in incoming.items():

            existing = self._events.get(event_id)

            merged = self._merge(existing, candidate)

            if merged != existing:
                self._events[event_id] = merged
                changed.add(event_id)

        return changed

    # ------------------------------------------------------------------
    # Merge helpers
    # ------------------------------------------------------------------

    def _merge(
        self,
        existing: OnwinEventState | None,
        candidate: OnwinEventState,
    ) -> OnwinEventState:

        if existing is None:
            return candidate

        home_odds, home_updated_at = self._pick_newer(
            existing.home_odds, existing.home_updated_at,
            candidate.home_odds, candidate.home_updated_at,
        )

        draw_odds, draw_updated_at = self._pick_newer(
            existing.draw_odds, existing.draw_updated_at,
            candidate.draw_odds, candidate.draw_updated_at,
        )

        away_odds, away_updated_at = self._pick_newer(
            existing.away_odds, existing.away_updated_at,
            candidate.away_odds, candidate.away_updated_at,
        )

        return replace(
            existing,
            # Update-feed responses don't include tournament/category
            # names (per the forensic analysis), so an empty competition
            # from the update payload must not overwrite a known one.
            competition=candidate.competition or existing.competition,
            status=candidate.status or existing.status,
            start_time_ms=candidate.start_time_ms or existing.start_time_ms,
            home_team=candidate.home_team or existing.home_team,
            home_team_id=candidate.home_team_id or existing.home_team_id,
            away_team=candidate.away_team or existing.away_team,
            away_team_id=candidate.away_team_id or existing.away_team_id,
            home_odds=home_odds,
            draw_odds=draw_odds,
            away_odds=away_odds,
            home_updated_at=home_updated_at,
            draw_updated_at=draw_updated_at,
            away_updated_at=away_updated_at,
        )

    @staticmethod
    def _pick_newer(old_val, old_ts, new_val, new_ts):
        """
        Decide whether an incoming outcome value should replace the
        stored one.

        - No incoming value (market/outcome absent from this payload)
          -> keep the old value. This is the ABSENCE RULE.
        - No usable timestamps to compare -> trust the new value, since
          it was still present in a response.
        - Otherwise only accept the new value if its updatedAt is not
          older than what's already stored, guarding against an
          out-of-order/stale response overwriting a newer value.
        """

        if new_val is None:
            return old_val, old_ts

        if old_val is None or old_ts is None or new_ts is None:
            return new_val, new_ts

        if new_ts >= old_ts:
            return new_val, new_ts

        return old_val, old_ts

    # ------------------------------------------------------------------
    # Payload walking (shared by load_initial and apply_update)
    # ------------------------------------------------------------------

    def _walk_football(self, raw_json: dict, out: dict[str, OnwinEventState]):

        football = raw_json.get("sports", {}).get(FOOTBALL_SPORT_ID)

        if not football:
            return

        for category in football.get("categories", {}).values():

            category_name = category.get("diff", {}).get("name", "")

            for tournament in category.get("tournaments", {}).values():

                competition = tournament.get("diff", {}).get(
                    "name",
                    category_name,
                )

                for event_id, event in tournament.get("events", {}).items():

                    state = self._extract_event_state(
                        event_id,
                        event,
                        competition,
                    )

                    if state is not None:
                        out[event_id] = state

    def _extract_event_state(
        self,
        event_id: str,
        event: dict,
        competition: str,
    ) -> OnwinEventState | None:

        event_fields = extract_event_diff(event)

        if event_fields is None:
            return None

        home_odds = draw_odds = away_odds = None
        home_updated_at = draw_updated_at = away_updated_at = None

        market = extract_1x2_market(event)

        if market is not None:
            home_odds, draw_odds, away_odds, updated_at = market
            home_updated_at = updated_at.get("p1")
            draw_updated_at = updated_at.get("draw")
            away_updated_at = updated_at.get("p2")

            # OnWin's "coefficient" field is already a JSON number, not
            # a string -- float() below is a no-op for precision, so
            # RAW and PARSED are traced as the same value (unlike
            # BetKanyon, there's no separate raw-string stage here).
            odds_trace.record(
                "PARSED",
                "OnWin",
                event_fields["home_team"],
                event_fields["away_team"],
                "1X2",
                None,
                home_odds,
                draw_odds,
                away_odds,
            )

        return OnwinEventState(
            event_id=event_id,
            competition=competition,
            status=event_fields["status"],
            start_time_ms=event_fields["start_time_ms"],
            home_team=event_fields["home_team"],
            home_team_id=event_fields["home_team_id"],
            away_team=event_fields["away_team"],
            away_team_id=event_fields["away_team_id"],
            home_odds=home_odds,
            draw_odds=draw_odds,
            away_odds=away_odds,
            home_updated_at=home_updated_at,
            draw_updated_at=draw_updated_at,
            away_updated_at=away_updated_at,
        )

    @staticmethod
    def _extract_version(raw_json: dict) -> int | None:

        versions = raw_json.get("versions")

        if isinstance(versions, list) and versions:
            return versions[0]

        return None

    # ------------------------------------------------------------------
    # MatchOdds generation
    # ------------------------------------------------------------------

    def get_match_odds(self, event_ids=None) -> list[MatchOdds]:
        """
        Rebuild MatchOdds from local state.

        This never touches the network or re-walks any raw JSON feed --
        it only reads already-extracted fields held in memory. Pass
        `event_ids` to regenerate a subset (e.g. only the events an
        update just changed); omit it to get the full current list.
        """

        if event_ids is None:
            targets = list(self._events.values())
        else:
            targets = [
                self._events[event_id]
                for event_id in event_ids
                if event_id in self._events
            ]

        results = []

        for state in targets:
            match_odds = self._state_to_match_odds(state)

            if match_odds is not None:
                results.append(match_odds)

        return results

    @staticmethod
    def _state_to_match_odds(state: OnwinEventState) -> MatchOdds | None:

        # Preserve the existing parser's semantics: only live matches
        # are surfaced as MatchOdds.
        if state.status != "in_progress":
            return None

        if None in (state.home_odds, state.draw_odds, state.away_odds):
            return None

        if state.start_time_ms is None:
            return None

        start_time = datetime.fromtimestamp(
            state.start_time_ms / 1000,
            tz=timezone.utc,
        )

        return MatchOdds(
            bookmaker="OnWin",
            competition=state.competition,
            sport="football",
            market="1X2",
            home_team=state.home_team,
            away_team=state.away_team,
            home_odds=state.home_odds,
            draw_odds=state.draw_odds,
            away_odds=state.away_odds,
            start_time=start_time,
            collected_at=datetime.now(timezone.utc),
        )

    def all_event_ids(self) -> set[str]:
        return set(self._events.keys())

    def get_event(self, event_id: str) -> OnwinEventState | None:
        return self._events.get(event_id)
