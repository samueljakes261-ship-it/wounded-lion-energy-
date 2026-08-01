import json

from parsers.kolay90_parser import Kolay90Parser


def main():

    print()

    print("=" * 60)
    print("KOLAY90 PARSER TEST")
    print("=" * 60)
    print()

    with open(

        "simulator/output/kolay90.json",

        encoding="utf-8"

    ) as f:

        data = json.load(f)

    parser = Kolay90Parser()

    matches = parser.parse(data)

    print(f"Matches Parsed: {len(matches)}")
    print()

    for match in matches:

        print("Bookmaker :", match.bookmaker)
        print("Competition :", match.competition)
        print("Sport :", match.sport)
        print("Market :", match.market)
        print("Match :", match.home_team, "vs", match.away_team)
        print(
            "Odds :",
            match.home_odds,
            "|",
            match.draw_odds,
            "|",
            match.away_odds
        )
        print("Start :", match.start_time)
        print("Collected :", match.collected_at)
        print()


if __name__ == "__main__":
    main()