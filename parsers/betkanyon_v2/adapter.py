from datetime import datetime, timezone

from models.match import MatchOdds


class BetkanyonAdapter:

    @staticmethod
    def to_match_odds(event):

        kickoff = event["kickoff"]

        # Handle ISO dates from BetKanyon
        if isinstance(kickoff, str):

            kickoff = datetime.fromisoformat(
                kickoff.replace("Z", "+00:00")
            )

        # Handle unix timestamps (kept for compatibility)
        elif isinstance(kickoff, (int, float)):

            kickoff = datetime.fromtimestamp(
                kickoff / 1000,
                tz=timezone.utc,
            )

        return MatchOdds(

            bookmaker="Betkanyon",

            competition=event["competition"],

            sport=event["sport"],

            market="Match Odds",

            home_team=event["home"],

            away_team=event["away"],

            home_odds=float(event["home_odds"]),

            draw_odds=float(event["draw_odds"]),

            away_odds=float(event["away_odds"]),

            start_time=kickoff,

            collected_at=datetime.now(timezone.utc),

        )