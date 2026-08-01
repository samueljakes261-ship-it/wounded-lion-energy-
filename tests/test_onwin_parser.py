import json

from parsers.onwin_parser import OnWinParser


def main():

    print()
    print("=" * 60)
    print("ONWIN PARSER TEST")
    print("=" * 60)
    print()

    with open(

        "simulator/output/onwin.json",

        encoding="utf-8"

    ) as file:

        data = json.load(file)

    matches = OnWinParser().parse(data)

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