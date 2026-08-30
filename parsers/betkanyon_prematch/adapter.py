from datetime import datetime, timezone

from models.match import MatchOdds


class BetkanyonPrematchAdapter:
    @staticmethod
    def to_match_odds(event, tournament_id=None):
        kickoff = event["kickoff"]

        if isinstance(kickoff, str):
            kickoff = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        elif isinstance(kickoff, (int, float)):
            kickoff = datetime.fromtimestamp(kickoff / 1000, tz=timezone.utc)

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
            feed_type="prematch",
            tournament_id=str(tournament_id) if tournament_id is not None else None,
        )
