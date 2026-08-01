from parsers.betkanyon.api import BetkanyonAPI
from parsers.betkanyon.decryptor import BetkanyonDecryptor


class TournamentCollector:

    def __init__(self):

        self.api = BetkanyonAPI()
        self.decryptor = BetkanyonDecryptor()

    def run(self):

        self.api.initialize()

        print()
        print("Downloading tournaments...")

        encrypted = self.api.fetch_tournaments()

        print()
        print("Decrypting tournaments...")

        tournaments = self.decryptor.decrypt(encrypted)

        self.api.close()

        return tournaments


if __name__ == "__main__":

    collector = TournamentCollector()

    tournaments = collector.run()

    print()

    print("Tournament count:", len(tournaments))

    print()

    for t in tournaments[:20]:
        print(
            t.get("Id"),
            "-",
            t.get("N"),
        )