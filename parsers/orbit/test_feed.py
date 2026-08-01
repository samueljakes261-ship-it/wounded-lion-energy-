import asyncio

from parsers.orbit.feed import OrbitFeed


async def main():

    feed = OrbitFeed()

    print("Collecting Orbit...\n")

    await feed.collect_once()

    matches = feed.get_match_odds()

    print(f"\nTotal MatchOdds: {len(matches)}\n")

    print("=" * 60)

    for match in matches:
        print(match)
        print()


if __name__ == "__main__":
    asyncio.run(main())