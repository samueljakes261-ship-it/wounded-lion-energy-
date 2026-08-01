import json

from parsers.orbit_parser import OrbitParser
from parsers.betfair_parser import BetfairParser
from parsers.kolay90_parser import Kolay90Parser


def main():

    print()
    print("=" * 70)
    print("MULTI BOOKMAKER PIPELINE")
    print("=" * 70)
    print()

    # -------------------------------
    # Orbit
    # -------------------------------

    with open(
        "simulator/output/orbit.json",
        encoding="utf-8"
    ) as f:

        orbit_data = json.load(f)

    orbit_matches = OrbitParser().parse(orbit_data)

    # -------------------------------
    # Betfair
    # -------------------------------

    with open(
        "simulator/output/betfair.json",
        encoding="utf-8"
    ) as f:

        betfair_data = json.load(f)

    betfair_matches = BetfairParser().parse(betfair_data)

    # -------------------------------
    # Kolay90
    # -------------------------------

    with open(
        "simulator/output/kolay90.json",
        encoding="utf-8"
    ) as f:

        kolay_data = json.load(f)

    kolay_matches = Kolay90Parser().parse(kolay_data)

    # -------------------------------

    all_matches = (

        orbit_matches +

        betfair_matches +

        kolay_matches

    )

    print(f"Orbit Matches    : {len(orbit_matches)}")
    print(f"Betfair Matches  : {len(betfair_matches)}")
    print(f"Kolay90 Matches  : {len(kolay_matches)}")

    print()

    print(f"TOTAL MATCHES : {len(all_matches)}")

    print()

    for match in all_matches:

        print(

            f"{match.bookmaker:<15}"

            f"{match.home_team:<20}"

            f"vs "

            f"{match.away_team:<20}"

            f"{match.home_odds} | "

            f"{match.draw_odds} | "

            f"{match.away_odds}"

        )


if __name__ == "__main__":
    main()