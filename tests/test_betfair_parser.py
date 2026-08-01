from parsers.betfair_parser import BetfairParser
from sources.betfair_source import BetfairSource


def main():

    print()
    print("=" * 60)
    print("BETFAIR PARSER TEST")
    print("=" * 60)
    print()

    raw_json = BetfairSource().load()

    parser = BetfairParser()

    matches = parser.parse(raw_json)

    print(f"Matches Parsed: {len(matches)}")
    print()

    for match in matches:

        print(f"Bookmaker : {match.bookmaker}")
        print(f"Competition : {match.competition}")
        print(f"Sport : {match.sport}")
        print(f"Market : {match.market}")
        print(f"Match : {match.home_team} vs {match.away_team}")
        print(
            f"Odds : {match.home_odds} | {match.draw_odds} | {match.away_odds}"
        )
        print()


if __name__ == "__main__":
    main()