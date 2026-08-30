import asyncio
import time

from collector import (
    ENGINE_TICK_SECONDS,
    collect_opportunities,
    start_prematch_workers,
    start_workers,
    stop_betkanyon_prematch_worker,
    stop_betkanyon_worker,
    stop_kolay90_prematch_worker,
    stop_onwin_prematch_worker,
    stop_onwin_worker,
    stop_orbit_prematch_worker,
    stop_orbit_worker,
)
from engine.recovery import restart_due
from prematch.mode import is_prematch_only


async def restart_workers_gracefully():
    """Stop then start the existing workers. Does not kill this process.

    Kolay90 close() detaches CDP only; the authenticated Chrome stays open.
    """
    from engine.recovery import begin_scheduled_restart, end_scheduled_restart

    begin_scheduled_restart()
    try:
        stop_onwin_worker()
        stop_betkanyon_worker()
        await stop_orbit_worker()
        stop_betkanyon_prematch_worker()
        await stop_orbit_prematch_worker()
        stop_kolay90_prematch_worker()
        stop_onwin_prematch_worker()
        if is_prematch_only():
            start_prematch_workers()
        else:
            start_workers()
            start_prematch_workers()
    finally:
        end_scheduled_restart()


async def main():

    print()
    print("=" * 70)
    print("ARBITRAGE ENGINE")
    print("=" * 70)
    print()
    if is_prematch_only():
        print("PREMATCH-ONLY MODE: live BetKanyon/Orbit/OnWin workers are frozen.")
        print("Set ENGINE_MODE=live and restart to restore the live pipeline.")
        print()
        start_prematch_workers()
    else:
        print("Starting persistent bookmaker workers (live + prematch)...")
        print("Live BetKanyon/Orbit/OnWin continue independently of prematch.")
        print()
        start_workers()
        start_prematch_workers()

    cycle_started = time.monotonic()
    try:
        while True:

            try:
                await collect_opportunities()
                if restart_due(cycle_started):
                    await restart_workers_gracefully()
                    cycle_started = time.monotonic()

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
        await stop_orbit_worker()
        stop_betkanyon_prematch_worker()
        await stop_orbit_prematch_worker()
        stop_kolay90_prematch_worker()
        stop_onwin_prematch_worker()
        print("Workers stopped. Goodbye.")


if __name__ == "__main__":

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
