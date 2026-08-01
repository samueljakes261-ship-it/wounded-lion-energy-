import json

from parsers.novel34_parser import Novel34Parser


def main():

    print()
    print("=" * 60)
    print("NOVEL34 PARSER TEST")
    print("=" * 60)
    print()

    with open(
        "simulator/output/novel34.json",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    matches = Novel34Parser().parse(data)

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