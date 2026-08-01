import json

from parsers.betkanyon_parser import BetKanyonParser


def main():

    print()
    print("=" * 60)
    print("BETKANYON PARSER TEST")
    print("=" * 60)
    print()

    with open(
        "simulator/output/betkanyon.json",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    matches = BetKanyonParser().parse(data)

    print(f"Matches Parsed : {len(matches)}")
    print()

    for match in matches:

        print(match.bookmaker)
        print(match.competition)
        print(match.home_team, "vs", match.away_team)
        print(match.home_odds, "|", match.draw_odds, "|", match.away_odds)
        print()

    print("=" * 60)


if __name__ == "__main__":
    main()