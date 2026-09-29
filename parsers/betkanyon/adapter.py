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

        if event.get("market") == "over_under" or event.get("line") is not None:
            over_odds = float(event.get("over_odds", event["home_odds"]))
            under_odds = float(event.get("under_odds", event["away_odds"]))
            return MatchOdds(
                bookmaker="Betkanyon",
                competition=event["competition"],
                sport=event["sport"],
                market="over_under",
                home_team=event["home"],
                away_team=event["away"],
                home_odds=over_odds,
                draw_odds=0.0,
                away_odds=under_odds,
                start_time=kickoff,
                collected_at=datetime.now(timezone.utc),
                line=float(event["line"]),
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