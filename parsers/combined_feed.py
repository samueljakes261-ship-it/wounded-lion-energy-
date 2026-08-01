from parsers.orbit.feed import OrbitFeed
from parsers.betkanyon.feed import BetkanyonFeed


class CombinedFeed:

    def __init__(self):

        self.orbit = OrbitFeed()

        self.betkanyon = BetkanyonFeed()

    def collect(self):

        orbit_matches = self.orbit.collect_once()

        betkanyon_matches = self.betkanyon.collect_once()

        print()

        print(f"Orbit      : {len(orbit_matches)}")

        print(f"Betkanyon  : {len(betkanyon_matches)}")

        print(f"Combined   : {len(orbit_matches)+len(betkanyon_matches)}")

        return orbit_matches + betkanyon_matches