from parsers.onwin.parser import OnWinParser
from engine.match_finder import MatchFinder


ONWIN_FILE = "output/onwin_main_line.json"


def main():
    # 1. Parse OnWin into canonical MatchOdds objects
    onwin_matches = OnWinParser().parse_file(ONWIN_FILE)

    print(f"OnWin MatchOdds: {len(onwin_matches)}")

    # 2. Feed MatchOdds into the existing matcher
    finder = MatchFinder()

    matched_events = finder.find(onwin_matches)

    print(f"Matched events: {len(matched_events)}")

    # 3. Display the results
    for event in matched_events:
        print(event)


if __name__ == "__main__":
    main()