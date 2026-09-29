"""Standalone Kolay90 prematch attach/poll helper.

Attaches to the existing authenticated Chrome on 127.0.0.1:9222.
Does not use ZenRows or CredentialManager. Does not close Chrome.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / ".env.local", override=True)

from parsers.kolay90_prematch.feed import Kolay90PrematchFeed


def log(message: str) -> None:
    print(f"[KOLAY90 PREMATCH] {message}", flush=True)


def mask_ws_source() -> str:
    raw = (os.environ.get("ZENROWS_BROWSER_WS") or "").strip()
    if not raw:
        return "source=ZENROWS_BROWSER_WS credential=(missing)"
    pairs = parse_qsl(urlsplit(raw).query, keep_blank_values=True)
    tail = "????"
    for key, value in pairs:
        if key.lower() in ("apikey", "api_key") and value:
            tail = value[-4:]
            break
    return f"source=ZENROWS_BROWSER_WS credential=********{tail}"


def cycle_line(n: int, result: dict) -> None:
    log(
        f"cycle {n} status={result.get('status')} "
        f"content_type={result.get('content_type')} "
        f"bytes={result.get('bytes')} "
        f"total_events={result.get('total_events')} "
        f"any_1x2={result.get('with_any_1x2')} "
        f"all_1x2={result.get('with_all_1x2')} "
        f"parsed={result.get('one_x_two')} "
        f"authenticated={result.get('authenticated')} "
        f"ok={result.get('ok')} "
        f"failure={result.get('failure')}"
    )


def mapping_samples(matches, limit: int = 3) -> None:
    log("Odds mapping 1=HOME 0=DRAW 2=AWAY")
    for index, row in enumerate(matches[:limit], start=1):
        print(
            f"  Event {index}: {row.home_team} vs {row.away_team} | "
            f"HOME={row.home_odds} DRAW={row.draw_odds} AWAY={row.away_odds}",
            flush=True,
        )


def main() -> int:
    log("Attaching to existing Chrome on 127.0.0.1:9222")
    feed = Kolay90PrematchFeed()
    started = feed.attach()
    log(f"title={started.get('title')} url={started.get('url')}")
    if not started.get("ok"):
        log(f"ATTACH_FAILED failure={started.get('failure')}")
        return 1

    results = []
    first = feed.poll()
    results.append(first)
    cycle_line(1, first)

    for n in (2, 3):
        time.sleep(8)
        row = feed.poll()
        results.append(row)
        cycle_line(n, row)

    log("Waiting 90 seconds before follow-up poll (same browser, no re-login)")
    time.sleep(90)
    fourth = feed.poll()
    results.append(fourth)
    cycle_line(4, fourth)

    matches = feed.last_good()
    if matches:
        mapping_samples(matches)

    expired = any(r.get("failure") == "login_expired" for r in results)
    if expired:
        log("KOLAY90_SESSION_EXPIRED")

    success = all(r.get("ok") and r.get("authenticated") for r in results) and bool(matches)
    if success:
        log("PERSISTENT_AUTHENTICATED_BROWSER_ACCESS = SUCCESS")
        log("ZENROWS_PER_POLL_REQUIRED = NO")
    else:
        log("PERSISTENT_AUTHENTICATED_BROWSER_ACCESS = FAILED")
        log(f"degraded={feed.degraded()}")

    log("Browser restarted=NO login_repeated=NO zenrows_recreated=NO")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
