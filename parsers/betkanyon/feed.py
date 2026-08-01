from parsers.betkanyon.fetcher import BetkanyonFetcher
from parsers.betkanyon.decryptor import BetkanyonDecryptor
from parsers.betkanyon.parser import parse_json
from parsers.betkanyon.adapter import BetkanyonAdapter


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

        #
        # DEBUG
        #
        print("\n================ BETKANYON MATCHES ================\n")

        for match in self._match_odds:

            print(match)
            print()

        return matches

    def get_match_odds(self):

        return self._match_odds

    def close(self):

        self.fetcher.close()