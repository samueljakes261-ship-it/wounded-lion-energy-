import re
import unicodedata

from resources.competition_aliases import COMPETITION_ALIASES


class CompetitionNormalizer:

    def normalize(self, name: str) -> str:

        if not name:
            return ""

        value = name

        #
        # Remove accents
        #

        value = "".join(

            c

            for c in unicodedata.normalize("NFKD", value)

            if not unicodedata.combining(c)

        )

        #
        # Lowercase
        #

        value = value.lower()

        #
        # Remove punctuation
        #

        value = re.sub(r"[^\w\s]", "", value)

        #
        # Collapse whitespace
        #

        value = re.sub(r"\s+", " ", value).strip()

        #
        # Apply aliases
        #

        return COMPETITION_ALIASES.get(value, value)