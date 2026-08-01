from models.match import MatchOdds


class MatchRepository:
    """
    Stores MatchOdds objects from all bookmakers.
    """

    def __init__(self):

        self._matches: list[MatchOdds] = []

    def add_matches(self, matches: list[MatchOdds]) -> None:
        """
        Adds multiple matches to the repository.
        """

        self._matches.extend(matches)

    def get_all(self) -> list[MatchOdds]:
        """
        Returns every stored match.
        """

        return self._matches

    def get_by_bookmaker(self, bookmaker: str) -> list[MatchOdds]:
        """
        Returns matches belonging to one bookmaker.
        """

        return [
            match
            for match in self._matches
            if match.bookmaker == bookmaker
        ]

    def clear(self) -> None:
        """
        Removes every stored match.
        """

        self._matches.clear()