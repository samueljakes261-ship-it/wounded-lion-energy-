import time

from parsers.betkanyon.feed import BetkanyonFeed


feed = BetkanyonFeed()

while True:

    print()

    print("========================================")
    print("NEW BETKANYON POLLING CYCLE")
    print("========================================")

    try:

        matches = feed.collect_once()

        print()

        print(f"Parsed MatchOdds : {len(matches)}")

        if matches:

            print()

            print(matches[0])

    except Exception as e:

        print()

        print("Cycle failed:")

        print(e)

    print()

    print("Next refresh in 20 seconds...")

    time.sleep(20)