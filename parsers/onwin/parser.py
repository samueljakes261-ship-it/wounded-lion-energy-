import json
from datetime import datetime, timezone
from pathlib import Path

from models.match import MatchOdds


# OnWin's football sport ID
FOOTBALL_SPORT_ID = "d6934640-cf1d-11e9-864b-0242ac13000a"


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

                    event_diff = event.get("diff", {})

                    # We only want live matches.
                    if event_diff.get("status") != "in_progress":
                        continue

                    participants = event_diff.get("participants", {})

                    team1 = participants.get("team1", {})
                    team2 = participants.get("team2", {})

                    home_team = team1.get("name")
                    away_team = team2.get("name")

                    if not home_team or not away_team:
                        continue

                    # The betting markets are under normal_time--0.
                    normal_time = event.get("scopes", {}).get(
                        "normal_time--0",
                        {}
                    )

                    markets = normal_time.get("markets", {})

                    # We only need the canonical 1X2 market.
                    match_1x2 = markets.get("score_1x2--nil")

                    if not match_1x2:
                        continue

                    outcomes = match_1x2.get("outcomes", {})

                    home_outcome = outcomes.get("outcome::p1")
                    draw_outcome = outcomes.get("outcome::draw")
                    away_outcome = outcomes.get("outcome::p2")

                    # A valid 1X2 market must contain all three outcomes.
                    if not home_outcome or not draw_outcome or not away_outcome:
                        continue

                    home_odds = home_outcome.get("coefficient")
                    draw_odds = draw_outcome.get("coefficient")
                    away_odds = away_outcome.get("coefficient")

                    if None in (home_odds, draw_odds, away_odds):
                        continue

                    # OnWin timestamps are Unix milliseconds.
                    start_time_ms = event_diff.get("startTime")

                    if start_time_ms is None:
                        continue

                    start_time = datetime.fromtimestamp(
                        start_time_ms / 1000,
                        tz=timezone.utc,
                    )

                    matches.append(
                        MatchOdds(
                            bookmaker="OnWin",
                            competition=competition,
                            sport="football",
                            market="1X2",
                            home_team=home_team,
                            away_team=away_team,
                            home_odds=float(home_odds),
                            draw_odds=float(draw_odds),
                            away_odds=float(away_odds),
                            start_time=start_time,
                            collected_at=datetime.now(timezone.utc),
                        )
                    )

        return matches