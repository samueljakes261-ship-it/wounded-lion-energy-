from parsers.betkanyon.api import BetkanyonAPI
from parsers.betkanyon.decryptor import BetkanyonDecryptor
from parsers.betkanyon.parser import parse_json


class BetkanyonCollector:

    def __init__(self):

        self.api = BetkanyonAPI()

        self.decryptor = BetkanyonDecryptor()

    def run(self):

        ####################################################
        # Step 1
        ####################################################

        self.api.initialize()

        encrypted = self.api.fetch_top_events()

        ####################################################
        # Step 2
        ####################################################

        print()
        print("Decrypting payload...")

        events = self.decryptor.decrypt(encrypted)

        ####################################################
        # Step 3
        ####################################################

        print()
        print("Parsing matches...")

        matches = parse_json(events)

        self.api.close()

        return matches


if __name__ == "__main__":

    collector = BetkanyonCollector()

    matches = collector.run()

    print()
    print("=" * 70)
    print(f"Found {len(matches)} football matches.")
    print("=" * 70)

    for match in matches:

        print()

        print("---------------------------------------")

        print(f"{match['home']} vs {match['away']}")

        print(f"Kickoff: {match['kickoff']}")

        print(
            f"Home: {match['home_odds']} | "
            f"Draw: {match['draw_odds']} | "
            f"Away: {match['away_odds']}"
        )