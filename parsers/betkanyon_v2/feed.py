from parsers.betkanyon_v2.fetcher import BetkanyonFetcher
from parsers.betkanyon_v2.decryptor import BetkanyonDecryptor
from parsers.betkanyon_v2.parser import parse_json
from parsers.betkanyon_v2.adapter import BetkanyonAdapter


class BetkanyonFeed:

    def __init__(self):

        self.fetcher = BetkanyonFetcher()

        self.decryptor = BetkanyonDecryptor()

        self._match_odds = []

    def collect_once(self):

        print("Fetching encrypted payload...")

        encrypted = self.fetcher.fetch()

        print("Decrypting payload...")

        decrypted = self.decryptor.decrypt(encrypted)

        print("Parsing events...")

        parsed = parse_json(decrypted)

        print(f"Parsed events : {len(parsed)}")

        matches = []

        for event in parsed:

            match = BetkanyonAdapter.to_match_odds(event)

            if match:

                matches.append(match)

        self._match_odds = matches

        print(f"Created MatchOdds : {len(matches)}")

        return matches

    def get_match_odds(self):

        return self._match_odds

    def close(self):

        self.fetcher.close()