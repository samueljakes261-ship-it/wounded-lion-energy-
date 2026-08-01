from simulator.bookmakers.orbit_simulator import OrbitSimulator
from simulator.bookmakers.betfair_simulator import BetfairSimulator
from simulator.bookmakers.kolay90_simulator import Kolay90Simulator
from simulator.bookmakers.novel34_simulator import Novel34Simulator
from simulator.bookmakers.betkanyon_simulator import BetKanyonSimulator
from simulator.bookmakers.onwin_simulator import OnWinSimulator


def main():

    print("=" * 70)
    print("BOOKMAKER SIMULATOR")
    print("=" * 70)
    print()

    simulators = [

        OrbitSimulator(),

        BetfairSimulator(),

        Kolay90Simulator(),

        Novel34Simulator(),

        BetKanyonSimulator(),

        OnWinSimulator()

    ]

    for simulator in simulators:

        print(f"Generating {simulator.bookmaker_name}...")

        simulator.generate()

    print()
    print("=" * 70)
    print("ALL BOOKMAKER DATA GENERATED")
    print("=" * 70)


if __name__ == "__main__":
    main()