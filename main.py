import json

from simulator.runner import main as generate_simulator_data

from parsers.orbit_parser import OrbitParser
from parsers.betfair_parser import BetfairParser
from parsers.kolay90_parser import Kolay90Parser
from parsers.novel34_parser import Novel34Parser
from parsers.betkanyon_parser import BetKanyonParser
from parsers.onwin_parser import OnWinParser

from services.scanner_service import ScannerService


BANKROLL = 1000


def load_json(path):

    with open(path, encoding="utf-8") as file:

        return json.load(file)


def run_pipeline():

    #
    # Generate fresh simulator data
    #

    generate_simulator_data()

    #
    # Parse every bookmaker
    #

    matches = []

    matches.extend(

        OrbitParser().parse(

            load_json("simulator/output/orbit.json")

        )

    )

    matches.extend(

        BetfairParser().parse(

            load_json("simulator/output/betfair.json")

        )

    )

    matches.extend(

        Kolay90Parser().parse(

            load_json("simulator/output/kolay90.json")

        )

    )

    matches.extend(

        Novel34Parser().parse(

            load_json("simulator/output/novel34.json")

        )

    )

    matches.extend(

        BetKanyonParser().parse(

            load_json("simulator/output/betkanyon.json")

        )

    )

    matches.extend(

        OnWinParser().parse(

            load_json("simulator/output/onwin.json")

        )

    )

    print(f"Total MatchOdds collected : {len(matches)}")
    print()

    scanner = ScannerService()

    opportunities = scanner.scan(

        matches=matches,

        bankroll=BANKROLL

    )

    return opportunities


def main():

    print()
    print("=" * 70)
    print("ARBITRAGE SCANNER")
    print("=" * 70)
    print()

    opportunities = run_pipeline()

    print("=" * 70)
    print("ARBITRAGE OPPORTUNITIES")
    print("=" * 70)
    print()

    if not opportunities:

        print("No arbitrage opportunities found.")
        return

    for opportunity in opportunities:

        event = opportunity.event
        result = opportunity.result
        plan = opportunity.stake_plan

        print(

            f"{event.home_team} vs {event.away_team}"

        )

        print(

            f"Profit : {result.profit_percentage:.2f}%"

        )

        print(

            f"ROI : {plan.roi:.2f}%"

        )

        print(

            f"Guaranteed Profit : {plan.guaranteed_profit:.2f}"

        )

        print("-" * 70)


if __name__ == "__main__":

    main()