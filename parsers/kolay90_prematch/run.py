"""Isolated Kolay90 prematch acquisition run.

Uses one persistent ZenRows browser. Does not close it.
Does not touch collector, run_engine, or other bookmakers.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from credentials.errors import AllCredentialsUnavailableError
from parsers.kolay90_prematch.feed import Kolay90PrematchFeed
from parsers.kolay90_prematch.login import credentials_configured


def log(message: str) -> None:
    print(f"[KOLAY90 PREMATCH] {message}")


def cycle_line(n: int, result: dict) -> None:
    log(
        f"cycle {n} status={result.get('status')} "
        f"content_type={result.get('content_type')} "
        f"bytes={result.get('bytes')} "
        f"total_events={result.get('total_events')} "
        f"1X2={result.get('one_x_two')} "
        f"parsed={result.get('one_x_two')} "
        f"ok={result.get('ok')} "
        f"failure={result.get('failure')}"
    )


def mapping_samples(matches, limit: int = 6) -> None:
    log("Odds mapping 1=HOME 0=DRAW 2=AWAY")
    for row in matches[:limit]:
        print(
            f"  {row.home_team} vs {row.away_team} | "
            f"1/HOME={row.raw_home} ({row.home_odds}) "
            f"0/DRAW={row.raw_draw} ({row.draw_odds}) "
            f"2/AWAY={row.raw_away} ({row.away_odds})"
        )


def main() -> int:
    if not credentials_configured():
        log("KOLAY90_USERNAME / KOLAY90_PASSWORD are not set")
        return 2
    log("Starting persistent ZenRows browser (will not close it)")
    feed = Kolay90PrematchFeed()
    try:
        started = feed.start()
    except AllCredentialsUnavailableError as exc:
        wait = float(exc.retry_after_seconds or 0)
        log(
            "ZenRows credential pool unavailable "
            f"(retry_after={int(wait)}s). Waiting for existing cooldown; "
            "not resetting credential rotation."
        )
        if wait > 0:
            time.sleep(wait + 5)
        started = feed.start()
    log(f"Cloudflare: {'CLEARED' if not started.get('cloudflare') else 'PRESENT'}")
    log(f"Login form submitted: {bool(started.get('login_form_submitted'))}")
    if not started.get("ok"):
        log(f"STOP: {started.get('reason')}")
        getmaclar = started.get("getmaclar") or {}
        log(f"getMaclar status={getmaclar.get('status')} unauth={getmaclar.get('unauthenticated')}")
        log("Leaving ZenRows browser open (not calling close())")
        if os.environ.get("KOLAY90_KEEP_ALIVE", "1").strip() not in ("0", "false", "no"):
            log("Idle keep-alive: session stays open; no further login attempts")
            while True:
                time.sleep(300)
        return 1

    results = []
    first = started.get("getmaclar") or {}
    first.setdefault("matches", feed.last_good())
    first.setdefault("ok", bool(first.get("authenticated")))
    results.append(first)
    cycle_line(1, first)

    for n in (2, 3):
        time.sleep(8)
        row = feed.poll()
        results.append(row)
        cycle_line(n, row)

    log("Waiting 90 seconds before follow-up poll (session stays open)")
    time.sleep(90)
    fourth = feed.poll()
    results.append(fourth)
    cycle_line(4, fourth)

    matches = feed.last_good()
    if matches:
        mapping_samples(matches)

    success = all(r.get("ok") and r.get("authenticated", r.get("ok")) for r in results)
    if success and matches:
        log("KOLAY90_PERSISTENT_PREMATCH_ACCESS = SUCCESS")
        log("ZenRows finding: session establishment only; polling used browser-context fetch")
    else:
        log("KOLAY90_PERSISTENT_PREMATCH_ACCESS = FAILED")
        log(f"degraded={feed.degraded()}")

    log("Leaving ZenRows browser open (not calling close())")
    if os.environ.get("KOLAY90_KEEP_ALIVE", "1").strip() not in ("0", "false", "no"):
        n = 5
        log("Keep-alive polling every 90s from the same browser context")
        while True:
            time.sleep(90)
            row = feed.poll()
            cycle_line(n, row)
            n += 1
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
