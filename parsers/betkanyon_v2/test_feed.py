import time

from parsers.betkanyon_v2.feed import BetkanyonFeed


feed = BetkanyonFeed()

while True:

    print("\n========================================")
    print("NEW BETKANYON V2 POLLING CYCLE")
    print("========================================")

    try:

        matches = feed.collect_once()

        print(f"\nMatchOdds created : {len(matches)}")

        if matches:

            print("\nFirst MatchOdds:\n")

            print(matches[0])

    except Exception as e:

        print("\nCycle failed:")

        print(e)

    print("\nNext refresh in 20 seconds...\n")

    time.sleep(20)