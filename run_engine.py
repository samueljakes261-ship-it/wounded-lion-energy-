import asyncio

from collector import collect_opportunities


REFRESH_SECONDS = 20


async def main():

    print()
    print("=" * 70)
    print("ARBITRAGE ENGINE")
    print("=" * 70)
    print()

    while True:

        try:

            opportunities = await collect_opportunities()

            print("=" * 70)
            print(f"SCAN COMPLETE | Opportunities Found: {len(opportunities)}")
            print("=" * 70)

            if opportunities:

                for opportunity in opportunities:

                    event = opportunity.event
                    result = opportunity.result
                    plan = opportunity.stake_plan

                    print()

                    print(
                        f"{event.home_team} vs {event.away_team}"
                    )

                    print(
                        f"{event.competition}"
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

                    print()

                    print(
                        f"HOME  -> {plan.home.bookmaker:<12}"
                        f"{plan.home.odds:<8}"
                        f"Stake {plan.home.stake}"
                    )

                    print(
                        f"DRAW  -> {plan.draw.bookmaker:<12}"
                        f"{plan.draw.odds:<8}"
                        f"Stake {plan.draw.stake}"
                    )

                    print(
                        f"AWAY  -> {plan.away.bookmaker:<12}"
                        f"{plan.away.odds:<8}"
                        f"Stake {plan.away.stake}"
                    )

                    print("-" * 70)

            else:

                print("No arbitrage opportunities found.")

        except Exception as e:

            print()
            print("=" * 70)
            print("ENGINE ERROR")
            print("=" * 70)
            print(e)

        print(f"\nNext scan in {REFRESH_SECONDS} seconds...\n")

        await asyncio.sleep(REFRESH_SECONDS)


if __name__ == "__main__":

    asyncio.run(main())