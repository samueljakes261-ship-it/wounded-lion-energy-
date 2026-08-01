from engine.normalizer import TeamNameNormalizer
from models.match import MatchOdds


class EventMatcher:
    """
    Temporary V1 matcher.

    Matches two events if the first three letters of the
    normalized home team and away team are the same.

    This is intentionally simple to prove the end-to-end
    arbitrage pipeline.
    """

    def __init__(self):

        self.normalizer = TeamNameNormalizer()

    def _prefix(self, team: str) -> str:

        team = self.normalizer.normalize(team)

        if not team:
            return ""

        first_word = team.split()[0]

        return first_word[:3]

    def is_same_event(
        self,
        match1: MatchOdds,
        match2: MatchOdds,
    ) -> bool:

        #
        # Football == Soccer
        #
        sport1 = match1.sport.lower()
        sport2 = match2.sport.lower()

        if sport1 == "soccer":
            sport1 = "football"

        if sport2 == "soccer":
            sport2 = "football"

        if sport1 != sport2:
            return False

        home1 = self._prefix(match1.home_team)
        away1 = self._prefix(match1.away_team)

        home2 = self._prefix(match2.home_team)
        away2 = self._prefix(match2.away_team)

        return (

            home1 == home2

            and

            away1 == away2

        )