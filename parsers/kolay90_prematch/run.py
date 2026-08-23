"""Isolated Kolay90 prematch acquisition run.

Uses one persistent ZenRows browser via ZENROWS_BROWSER_WS.
Does not use CredentialManager. Does not close the browser between polls.
Does not touch collector, run_engine, or other bookmakers.
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
from parsers.kolay90_prematch.login import credentials_configured


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
            f"HOME={row.raw_home} DRAW={row.raw_draw} AWAY={row.raw_away}",
            flush=True,
        )


def main() -> int:
    if not credentials_configured():
        log("KOLAY90_USERNAME / KOLAY90_PASSWORD are not set")
        return 2
    if not (os.environ.get("ZENROWS_BROWSER_WS") or "").strip():
        log("ZENROWS_BROWSER_WS is not set")
        return 2

    log("Starting one persistent ZenRows browser")
    log(mask_ws_source())
    feed = Kolay90PrematchFeed()
    started = feed.start()
    inspect = started.get("inspect") or {}
    log(f"title={started.get('page_title')}")
    log(f"path={started.get('page_path')}")
    log(f"cloudflare={started.get('cloudflare')} application={inspect.get('application')}")
    log(f"login_form_found={started.get('login_form_found')} submitted={started.get('login_form_submitted')}")
    log(f"input_types={inspect.get('input_types')} buttons={inspect.get('button_labels')}")

    if started.get("reason") == "KOLAY90_CLOUDFLARE_SESSION_FAILED" or started.get("cloudflare"):
        log("KOLAY90_CLOUDFLARE_SESSION_FAILED")
        return 4
    if not started.get("ok"):
        log(f"AUTHENTICATION_FAILED reason={started.get('reason')}")
        getmaclar = started.get("getmaclar") or {}
        cycle_line(1, getmaclar)
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
