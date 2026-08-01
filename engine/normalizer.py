import re
import unicodedata

from resources.aliases.common import COMMON
from resources.club_suffixes import CLUB_SUFFIXES


class TeamNameNormalizer:
    """
    Converts bookmaker team names into a canonical format.

    Normalization pipeline:

    Raw
        ↓
    Remove accents
        ↓
    Lowercase
        ↓
    Replace separators
        ↓
    Remove punctuation
        ↓
    Collapse whitespace
        ↓
    Remove club suffixes
        ↓
    Normalize common words
        ↓
    Apply aliases
        ↓
    Canonical name
    """

    def normalize(self, name: str, debug: bool = False) -> str:

        if not name:
            return ""

        value = name

        if debug:
            print("\nRAW")
            print(value)

        value = self._remove_accents(value)
        self._debug("ACCENTS", value, debug)

        value = self._to_lower(value)
        self._debug("LOWERCASE", value, debug)

        value = self._replace_separators(value)
        self._debug("SEPARATORS", value, debug)

        value = self._remove_punctuation(value)
        self._debug("PUNCTUATION", value, debug)

        value = self._collapse_spaces(value)
        self._debug("SPACES", value, debug)

        value = self._remove_suffixes(value)
        self._debug("SUFFIXES", value, debug)

        value = self._normalize_words(value)
        self._debug("WORDS", value, debug)

        value = self._apply_aliases(value)
        self._debug("ALIASES", value, debug)

        return value.strip()

    # ---------------------------------------------------
    # Individual stages
    # ---------------------------------------------------

    def _remove_accents(self, text: str) -> str:

        return "".join(
            c
            for c in unicodedata.normalize("NFKD", text)
            if not unicodedata.combining(c)
        )

    def _to_lower(self, text: str) -> str:

        return text.lower()

    def _replace_separators(self, text: str) -> str:

        separators = [
            "-",
            "_",
            "/",
            "\\",
            "|",
        ]

        for separator in separators:
            text = text.replace(separator, " ")

        return text

    def _remove_punctuation(self, text: str) -> str:

        return re.sub(r"[^\w\s]", "", text)

    def _collapse_spaces(self, text: str) -> str:

        return re.sub(r"\s+", " ", text).strip()

    def _remove_suffixes(self, text: str) -> str:

        words = text.split()

        while words and words[-1] in CLUB_SUFFIXES:
            words.pop()

        return " ".join(words)

    def _normalize_words(self, text: str) -> str:

        replacements = {

            "utd": "united",
            "st": "saint",

        }

        words = []

        for word in text.split():

            words.append(
                replacements.get(word, word)
            )

        return " ".join(words)

    def _apply_aliases(self, text: str) -> str:

        return COMMON.get(text, text)

    # ---------------------------------------------------
    # Debug helper
    # ---------------------------------------------------

    def _debug(self, stage: str, value: str, enabled: bool):

        if enabled:

            print(f"\n{stage}")
            print(value)