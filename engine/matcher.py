from engine.normalizer import TeamNameNormalizer
from models.match import MatchOdds


class EventMatcher:
    """
    Temporary V1 matcher.

    Matches two events if:

    1. They represent the same sport.
    2. Their normalized home-team prefixes match.
    3. Their normalized away-team prefixes match.

    The current V1 matching rule intentionally uses
    the first three letters of the first normalized
    team-name word.
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

        #
        # Normalize home and away teams
        #

        home1 = self._prefix(match1.home_team)
        away1 = self._prefix(match1.away_team)

        home2 = self._prefix(match2.home_team)
        away2 = self._prefix(match2.away_team)

        #
        # Compare home + away teams
        #

        return (
            home1 == home2
            and
            away1 == away2
        )