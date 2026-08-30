"""
Kenyan Bookmakers engine -- standalone startup command.

This is a NEW, isolated entry point. It does not import, modify, or
change the behavior of the existing `run_engine.py` in any way; the
existing Turkish/client-facing startup command continues to work
exactly as before.

USAGE
-----

    python run_kenyan_engine.py
    python run_kenyan_engine.py --mode kenyan          (same as above; explicit)
    python run_kenyan_engine.py --mode all             (Kenyan AND the existing
                                                          Orbit/BetKanyon/OnWin/
                                                          Kolay90 workers)

DEFAULT STARTUP = KENYAN_ONLY.

Running with no arguments (or `--mode kenyan`) starts ONLY:
    - SportPesa  (LIVE + PREMATCH)
    - Betika     (LIVE + PREMATCH)
    - 1xBet      (LIVE + PREMATCH)
    - 22Bet      (LIVE + PREMATCH)

It does NOT start Orbit, BetKanyon, OnWin, or Kolay90. Each of the four
Kenyan bookmakers is polled every 5 seconds by its own persistent
worker (see kenyan/workers/*.py) -- nothing here spins up a new
browser/process per poll.

`--mode all` additionally starts the EXISTING persistent workers via
`collector.start_workers()` (imported, not modified) so a future
"run everything" mode is available without ever having silently made
that the default.
"""
import argparse
import asyncio
import time

from kenyan.runner import get_runner


KENYAN_ONLY = "kenyan"
ALL_BOOKMAKERS = "all"

ENGINE_TICK_SECONDS = 5.0


def _print_header(mode: str):
    print()
    print("=" * 70)
    print("KENYAN BOOKMAKERS ARBITRAGE ENGINE")
    print("=" * 70)
    print(f"Mode: {mode.upper()}")
    print()

    if mode == KENYAN_ONLY:
        print("Starting persistent Kenyan workers ONLY:")
        print("  SportPesa, Betika, 1xBet, 22Bet (LIVE + PREMATCH each)")
        print("Orbit / BetKanyon / OnWin / Kolay90 are NOT started in this mode.")
    else:
        print("Starting persistent Kenyan workers:")
        print("  SportPesa, Betika, 1xBet, 22Bet (LIVE + PREMATCH each)")
        print("...AND the existing Turkish/global workers (Orbit / BetKanyon / OnWin).")
        print("(Reuses collector.start_workers() unmodified -- see collector.py.)")

    print("Each Kenyan feed polls its bookmaker every 5 seconds.")
    print("=" * 70)
    print()


def _print_worker_statuses(runner):
    statuses = runner.get_worker_statuses()
    for name in sorted(statuses):
        status = statuses[name]
        age = status["age_seconds"]
        age_str = f"{age:.1f}s" if age is not None else "n/a"
        print(
            f"  [{status['health']:<9}] {name:<22} "
            f"matches={status['match_count']:<3} age={age_str}"
        )


def _print_tick(runner):
    ts = time.strftime("%H:%M:%S")
    live_count = len(runner.get_live_opportunities())
    prematch_count = len(runner.get_prematch_opportunities())

    print(f"[KENYAN] {ts} | live_arbs={live_count} | prematch_arbs={prematch_count}")
    _print_worker_statuses(runner)
    print()


async def _run_kenyan_only():
    runner = get_runner()
    runner.start()

    try:
        while True:
            _print_tick(runner)
            await asyncio.sleep(ENGINE_TICK_SECONDS)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        runner.stop()


async def _run_all_bookmakers():
    # Imported lazily, and ONLY in --mode all, so `--mode kenyan`
    # (the default) never even imports the existing engine's
    # multiprocessing/Playwright-dependent modules.
    from collector import (
        collect_opportunities,
        start_workers,
        stop_betkanyon_worker,
        stop_onwin_worker,
    )

    runner = get_runner()
    runner.start()
    start_workers()  # existing Orbit/BetKanyon/OnWin workers, unmodified

    try:
        while True:
            _print_tick(runner)

            try:
                await collect_opportunities()
            except Exception as exc:  # noqa: BLE001 -- keep the Kenyan loop alive
                print(f"[EXISTING ENGINE ERROR] {exc}")

            await asyncio.sleep(ENGINE_TICK_SECONDS)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        runner.stop()
        stop_onwin_worker()
        stop_betkanyon_worker()


def main():
    parser = argparse.ArgumentParser(
        description="Kenyan Bookmakers arbitrage engine (isolated, own startup command)."
    )
    parser.add_argument(
        "--mode",
        choices=[KENYAN_ONLY, ALL_BOOKMAKERS],
        default=KENYAN_ONLY,
        help=(
            "kenyan (default): start ONLY SportPesa/Betika/1xBet/22Bet. "
            "all: also start the existing Orbit/BetKanyon/OnWin workers."
        ),
    )
    args = parser.parse_args()

    _print_header(args.mode)

    try:
        if args.mode == ALL_BOOKMAKERS:
            asyncio.run(_run_all_bookmakers())
        else:
            asyncio.run(_run_kenyan_only())
    except KeyboardInterrupt:
        pass

    print()
    print("Kenyan engine stopped. Goodbye.")


if __name__ == "__main__":
    main()
