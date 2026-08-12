import asyncio

from collector import (
    ENGINE_TICK_SECONDS,
    collect_opportunities,
    start_workers,
    stop_betkanyon_worker,
    stop_onwin_worker,
)


async def main():

    print()
    print("=" * 70)
    print("ARBITRAGE ENGINE")
    print("=" * 70)
    print()
    print("Starting persistent bookmaker workers (OnWin + BetKanyon)...")
    print("Both run concurrently and independently in the background.")
    print()

    # Explicitly kick off both persistent workers up front so they
    # start acquiring data CONCURRENTLY, rather than each only
    # appearing lazily whenever collect_opportunities() first happens
    # to touch it.
    start_workers()

    try:
        while True:

            try:
                await collect_opportunities()

            except Exception as e:
                print()
                print("=" * 70)
                print("ENGINE ERROR")
                print("=" * 70)
                print(e)

            # NOTE: this sleep only paces how often the engine
            # re-checks/re-matches whatever OnWin/BetKanyon have
            # already published -- it does NOT control bookmaker
            # freshness. OnWin patches its state continuously as
            # find_event_snapshots arrives; BetKanyon polls on its own
            # ~BETKANYON_POLL_INTERVAL cycle. Both keep running
            # regardless of this loop's pace.
            await asyncio.sleep(ENGINE_TICK_SECONDS)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print()
        print("Shutting down...")

    finally:
        stop_onwin_worker()
        stop_betkanyon_worker()
        print("Workers stopped. Goodbye.")


if __name__ == "__main__":

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
