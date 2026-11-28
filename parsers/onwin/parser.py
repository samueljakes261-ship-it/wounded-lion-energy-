import json
from datetime import datetime, timezone
from pathlib import Path

from models.markets import TARGET_OU_LINE, parse_ou_line_from_name
from models.match import MatchOdds


# OnWin's football sport ID
FOOTBALL_SPORT_ID = "d6934640-cf1d-11e9-864b-0242ac13000a"

# The market this project's arbitrage MVP tracks. Shared by the
# full-snapshot parser below and by parsers.onwin.state, so both read
# the exact same scope/market/outcome path.
ONWIN_1X2_SCOPE = "normal_time--0"
ONWIN_1X2_MARKET = "score_1x2--nil"
_MIN_OU_ODDS = 1.01
_MAX_OU_ODDS = 100.0


def extract_ou_2_5(event: dict) -> tuple[float, float, float, int | None] | None:
    """Over/Under 2.5 from the same normal_time--0 scope as 1X2.

    Confirmed on saved OnWin trees: market keys such as score_ou--2.5
    carry outcome::over and outcome::under coefficients. Other lines are
    left out so they cannot be mixed into the 2.5 book. A tree with no
    totals market returns None.
    """
    markets = (event.get("scopes") or {}).get(ONWIN_1X2_SCOPE, {}).get("markets") or {}
    if not isinstance(markets, dict):
        return None
    for key, market in markets.items():
        if not isinstance(market, dict):
            continue
        outcomes = market.get("outcomes") or {}
        if not isinstance(outcomes, dict):
            continue
        over = outcomes.get("outcome::over") or outcomes.get("over")
        under = outcomes.get("outcome::under") or outcomes.get("under")
        if not isinstance(over, dict) or not isinstance(under, dict):
            continue
        line = parse_ou_line_from_name(str(key))
        if line != TARGET_OU_LINE:
            continue
        try:
            over_price = float(over.get("coefficient"))
            under_price = float(under.get("coefficient"))
        except (TypeError, ValueError):
            continue
        if not (
            _MIN_OU_ODDS <= over_price <= _MAX_OU_ODDS
            and _MIN_OU_ODDS <= under_price <= _MAX_OU_ODDS
        ):
            continue
        updated = over.get("updatedAt")
        try:
            updated_at = int(updated) if updated is not None else None
        except (TypeError, ValueError):
            updated_at = None
        return line, over_price, under_price, updated_at
    return None


def extract_event_diff(event: dict) -> dict | None:
    """
    Pulls the event-level fields (status/participants/startTime) out of
    one event's "diff" block.

    This is intentionally the ONLY place that reads this shape, so both
    OnWinParser (full get_main_line snapshots) and OnwinState
    (incremental find_event_snapshots updates) stay in sync.

    Returns None when the event doesn't even carry usable participant
    names -- callers should skip such events rather than build an
    incomplete MatchOdds.
    """

    event_diff = event.get("diff", {})

    participants = event_diff.get("participants", {})

    team1 = participants.get("team1", {})
    team2 = participants.get("team2", {})

    home_team = team1.get("name")
    away_team = team2.get("name")

    if not home_team or not away_team:
        return None

    return {
        "status": event_diff.get("status"),
        "start_time_ms": event_diff.get("startTime"),
        "home_team": home_team,
        "home_team_id": team1.get("teamId"),
        "away_team": away_team,
        "away_team_id": team2.get("teamId"),
    }


def extract_1x2_market(event: dict):
    """
    Pulls home/draw/away coefficients (and their updatedAt) out of one
    event's normal_time--0 / score_1x2--nil market, if present.

    Returns None when the market or any of its three outcomes is
    missing from this payload. Per the forensic analysis of captured
    OnWin traffic, absence means "no information in this response", not
    "the market/outcome no longer exists" -- callers must not treat a
    None return as evidence of deletion.
    """

    normal_time = event.get("scopes", {}).get(ONWIN_1X2_SCOPE, {})

    markets = normal_time.get("markets", {})

    match_1x2 = markets.get(ONWIN_1X2_MARKET)

    if not match_1x2:
        return None

    outcomes = match_1x2.get("outcomes", {})

    home_outcome = outcomes.get("outcome::p1")
    draw_outcome = outcomes.get("outcome::draw")
    away_outcome = outcomes.get("outcome::p2")

    # A valid 1X2 market must contain all three outcomes.
    if not home_outcome or not draw_outcome or not away_outcome:
        return None

    home_odds = home_outcome.get("coefficient")
    draw_odds = draw_outcome.get("coefficient")
    away_odds = away_outcome.get("coefficient")

    if None in (home_odds, draw_odds, away_odds):
        return None

    return (
        float(home_odds),
        float(draw_odds),
        float(away_odds),
        {
            "p1": home_outcome.get("updatedAt"),
            "draw": draw_outcome.get("updatedAt"),
            "p2": away_outcome.get("updatedAt"),
        },
    )


class OnWinParser:
    """
    Parses live football 1X2 markets from an OnWin main-line JSON payload.
    """

    def parse_file(self, file_path: str | Path) -> list[MatchOdds]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.parse(data)

    def parse(self, data: dict) -> list[MatchOdds]:
        matches = []

        # Get football directly using the known football sport ID.
        football = data.get("sports", {}).get(FOOTBALL_SPORT_ID)

        if not football:
            return matches

        # Walk through all football categories.
        for category in football.get("categories", {}).values():

            category_name = category.get("diff", {}).get("name", "")

            # Walk through tournaments inside each category.
            for tournament in category.get("tournaments", {}).values():

                competition = tournament.get("diff", {}).get(
                    "name",
                    category_name
                )

                # Walk through every event.
                for event in tournament.get("events", {}).values():

                    event_fields = extract_event_diff(event)

                    if event_fields is None:
                        continue

                    # We only want live matches.
                    if event_fields["status"] != "in_progress":
                        continue

                    start_time_ms = event_fields["start_time_ms"]
                    if start_time_ms is None:
                        continue
                    start_time = datetime.fromtimestamp(
                        start_time_ms / 1000,
                        tz=timezone.utc,
                    )
                    collected = datetime.now(timezone.utc)

                    market = extract_1x2_market(event)
                    if market is not None:
                        home_odds, draw_odds, away_odds, _updated_at = market
                        matches.append(
                            MatchOdds(
                                bookmaker="OnWin",
                                competition=competition,
                                sport="football",
                                market="1X2",
                                home_team=event_fields["home_team"],
                                away_team=event_fields["away_team"],
                                home_odds=home_odds,
                                draw_odds=draw_odds,
                                away_odds=away_odds,
                                start_time=start_time,
                                collected_at=collected,
                            )
                        )

                    totals = extract_ou_2_5(event)
                    if totals is not None:
                        line, over_odds, under_odds, _updated = totals
                        matches.append(
                            MatchOdds(
                                bookmaker="OnWin",
                                competition=competition,
                                sport="football",
                                market="over_under",
                                home_team=event_fields["home_team"],
                                away_team=event_fields["away_team"],
                                home_odds=over_odds,
                                draw_odds=0.0,
                                away_odds=under_odds,
                                start_time=start_time,
                                collected_at=collected,
                                line=line,
                            )
                        )

        return matches
