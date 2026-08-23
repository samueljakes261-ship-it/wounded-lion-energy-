"""Manual Chrome + CDP attach experiment for Kolay90 getMaclar.

Launches a dedicated local Chrome, waits for the operator to finish
Cloudflare / agreement / login, then attaches to THAT process and
polls getMaclar from the same page context.

Does not use ZenRows, CredentialManager, cookie replay, or standalone HTTP.
Does not close Chrome. Does not modify production collectors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
PROFILE = HERE / "chrome_profile"
CDP_URL = "http://127.0.0.1:9222"
CDP_PORT = 9222
HOME = "https://kolay90.com/"

from parsers.kolay90_prematch.agreement import is_agreement_page
from parsers.kolay90_prematch.login import _looks_like_challenge, inspect_page
from parsers.kolay90_prematch.parser import (
    count_oranlar,
    is_unauthenticated,
    parse_payload,
    unwrap_events,
)
from parsers.kolay90_prematch.session_probe import safe_url


def log(message: str) -> None:
    safe = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[KOLAY90 MANUAL] {safe}", flush=True)


def redact(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"apikey=[^&\s]+", "apikey=***", value, flags=re.I)
    value = re.sub(r"__cf_chl[^=]*=[^&\s]+", "__cf_chl=***", value, flags=re.I)
    return value


def discover_chrome() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for path in candidates:
        if path and path.is_file():
            return path
    return None


def launch_command(chrome: Path) -> str:
    return (
        f'& "{chrome}" `\n'
        f"  --remote-debugging-port={CDP_PORT} `\n"
        f'  --user-data-dir="{PROFILE}" `\n'
        f"  {HOME}"
    )


def launch_chrome() -> Path:
    chrome = discover_chrome()
    if chrome is None:
        raise RuntimeError("Google Chrome executable was not found")
    PROFILE.mkdir(parents=True, exist_ok=True)
    print()
    print("Copy/paste if you need to start Chrome yourself:")
    print(launch_command(chrome))
    print()
    subprocess.Popen(
        [
            str(chrome),
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={PROFILE}",
            HOME,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return chrome


def print_manual_pause() -> None:
    print()
    print("=" * 50)
    print("MANUAL ACTION REQUIRED")
    print("=" * 50)
    print()
    print("Chrome is open.")
    print()
    print("Please manually:")
    print()
    print("1. Complete the Cloudflare challenge if displayed.")
    print("2. Wait until Kolay90 loads.")
    print("3. Accept the Kolay90 user agreement.")
    print("4. Log into Kolay90 using the credentials I provide.")
    print("5. Navigate to the normal authenticated Kolay90 application.")
    print()
    print("DO NOT CLOSE THE BROWSER.")
    print()
    print("When you have finished, return to the terminal and press ENTER.")
    print()
    print("=" * 50)
    print()


def wait_for_enter() -> None:
    try:
        input()
    except EOFError:
        log("No interactive stdin; continuing to attach")


def connect_existing_chrome():
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    return playwright, browser


def list_pages(browser) -> list[dict]:
    rows = []
    for context in browser.contexts:
        for page in context.pages:
            title = ""
            try:
                title = page.title() or ""
            except Exception:
                title = ""
            rows.append(
                {
                    "url": safe_url(page.url or ""),
                    "title": title[:120],
                    "page": page,
                }
            )
    return rows


def find_kolay90_page(rows: list[dict]):
    for row in rows:
        host = (urlsplit(row.get("url") or "").hostname or "").lower()
        if host == "kolay90.com" or host.endswith(".kolay90.com"):
            return row
    return None


def classify_session_state(
    url: str = "",
    title: str = "",
    text: str = "",
    has_password: bool = False,
    has_account: bool = False,
    has_login_control: bool = False,
    application: bool = False,
    cloudflare: bool = False,
) -> str:
    if cloudflare:
        return "CLOUDFLARE"
    if is_agreement_page(url, title, text):
        return "AGREEMENT"
    if has_password or (has_login_control and not has_account):
        return "LOGIN"
    if has_account or (application and not has_login_control):
        return "AUTHENTICATED_APP"
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("kolay90.com") or host == "kolay90.com":
        return "KOLAY90_UNKNOWN"
    return "UNKNOWN"


def classify_page(page) -> str:
    inspect = inspect_page(page)
    url = page.url or ""
    return classify_session_state(
        url=url,
        title=inspect.get("title") or "",
        text=inspect.get("text") or "",
        has_password=bool(inspect.get("has_password")),
        has_account=bool(inspect.get("has_account")),
        has_login_control=bool(inspect.get("has_login_control")),
        application=bool(inspect.get("application")),
        cloudflare=_looks_like_challenge(page) or bool(inspect.get("cloudflare")),
    )


def parse_in_page_response(result: dict) -> dict:
    """Turn the in-page fetch result into the shared getMaclar summary shape."""
    text = result.get("text") or ""
    content_type = result.get("contentType") or result.get("content_type")
    status = result.get("status")
    payload = None
    json_ok = False
    if text.lstrip()[:1] in "{[":
        try:
            payload = json.loads(text)
            json_ok = True
        except json.JSONDecodeError:
            payload = None
    looks_html = "text/html" in (content_type or "").lower() or text.lstrip()[:1] == "<"
    unauth = is_unauthenticated(payload) if json_ok else False
    return {
        "status": status,
        "content_type": content_type,
        "payload": payload,
        "unauthenticated": unauth,
        "cloudflare": bool(looks_html and status in (403, 503, 200) and not json_ok),
    }


def in_page_getmaclar(page) -> dict:
    result = page.evaluate(
        """async () => {
            const response = await fetch("https://kolay90.com/service/getMaclar");
            return {
                status: response.status,
                contentType: response.headers.get("content-type"),
                text: await response.text()
            };
        }"""
    )
    return parse_in_page_response(result)


def summarize_fetch(raw: dict) -> dict:
    payload = raw.get("payload")
    events = unwrap_events(payload)
    matches = parse_payload(payload)
    counts = count_oranlar(events)
    if raw.get("unauthenticated"):
        kind = "UNAUTHENTICATED_JSON"
        auth = "FAILED"
    elif raw.get("cloudflare") or raw.get("status") == 403:
        kind = "403"
        auth = "FAILED"
    elif events and not raw.get("unauthenticated"):
        kind = "AUTHENTICATED_JSON"
        auth = "OK"
    else:
        kind = "NOT_REACHED"
        auth = "FAILED"
    examples = []
    for row in matches[:3]:
        examples.append(
            {
                "home": row.home_team,
                "away": row.away_team,
                "HOME": row.raw_home,
                "DRAW": row.raw_draw,
                "AWAY": row.raw_away,
            }
        )
    return {
        "status": raw.get("status"),
        "content_type": raw.get("content_type"),
        "kind": kind,
        "authenticated": auth == "OK",
        "auth_label": auth,
        "total_events": len(events),
        "valid_1x2": counts["with_all_1x2"],
        "examples": examples,
    }


def classify_polls(rows: list[dict]) -> str:
    if not rows:
        return "E"
    if rows[0].get("kind") == "UNAUTHENTICATED_JSON":
        return "F"
    if rows[0].get("kind") == "403":
        return "G"
    if rows[0].get("kind") != "AUTHENTICATED_JSON":
        return "E"
    later = rows[1:]
    if later and any(not item.get("authenticated") for item in later):
        return "H"
    if len(rows) >= 4 and all(item.get("authenticated") for item in rows[:4]):
        return "I"
    return "E"


def print_poll(n: int, row: dict) -> None:
    log(
        f"REQUEST {n}: STATUS={row.get('status')} "
        f"CONTENT_TYPE={row.get('content_type')} "
        f"TOTAL_EVENTS={row.get('total_events')} "
        f"VALID_1X2_EVENTS={row.get('valid_1x2')} "
        f"AUTHENTICATED_JSON={'YES' if row.get('authenticated') else 'NO'}"
    )


def attach_and_poll() -> dict:
    result = {
        "cdp": "FAILED",
        "state": None,
        "polls": [],
        "long_polls": [],
        "boundary": "A",
        "access": "FAILED",
        "zenrows_polling": "UNKNOWN",
    }
    playwright = None
    try:
        playwright, browser = connect_existing_chrome()
        result["cdp"] = "SUCCESS"
        log("CDP_ATTACH=SUCCESS")
    except Exception as exc:
        log(f"CDP_ATTACH=FAILED {type(exc).__name__}")
        result["boundary"] = "A"
        return result

    try:
        rows = list_pages(browser)
        log(f"pages={len(rows)}")
        for row in rows:
            log(f"  title={row['title']!r} url={row['url']}")
        found = find_kolay90_page(rows)
        if found is None:
            log("MANUAL_SESSION_STATE=UNKNOWN no kolay90 tab")
            result["boundary"] = "E"
            return result
        page = found["page"]
        state = classify_page(page)
        result["state"] = state
        log(f"MANUAL_SESSION_STATE={state}")
        if state == "CLOUDFLARE":
            result["boundary"] = "B"
            return result
        if state == "AGREEMENT":
            result["boundary"] = "C"
            return result
        if state == "LOGIN":
            result["boundary"] = "D"
            return result
        if state != "AUTHENTICATED_APP":
            result["boundary"] = "E"
            return result

        waits = (0, 30, 30, 60)
        polls = []
        for index, wait_s in enumerate(waits, start=1):
            if wait_s:
                time.sleep(wait_s)
            row = summarize_fetch(in_page_getmaclar(page))
            polls.append(row)
            print_poll(index, row)
            if row.get("examples") and index == 1:
                for example in row["examples"]:
                    log(
                        f"HOME TEAM={example['home']} AWAY TEAM={example['away']} "
                        f"HOME ODDS={example['HOME']} DRAW ODDS={example['DRAW']} "
                        f"AWAY ODDS={example['AWAY']}"
                    )
        result["polls"] = polls
        boundary = classify_polls(polls)
        result["boundary"] = boundary
        if boundary != "I":
            result["access"] = "FAILED"
            result["zenrows_polling"] = "UNKNOWN"
            return result

        long_polls = []
        for index in range(1, 6):
            time.sleep(60)
            row = summarize_fetch(in_page_getmaclar(page))
            long_polls.append(row)
            log(
                f"LONG {index}: STATUS={row.get('status')} "
                f"TOTAL_EVENTS={row.get('total_events')} "
                f"VALID_1X2={row.get('valid_1x2')} "
                f"AUTH={'YES' if row.get('authenticated') else 'NO'}"
            )
        result["long_polls"] = long_polls
        long_ok = bool(long_polls) and all(item.get("authenticated") for item in long_polls)
        result["long_ok"] = long_ok
        result["access"] = "SUCCESS"
        result["zenrows_polling"] = "NO"
        if not long_ok:
            log("LONG_SESSION_TEST=FAILED after authenticated polls 1-4")
        return result
    finally:
        log("Leaving Chrome open")
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", action="store_true", help="Start Chrome only")
    parser.add_argument("--attach", action="store_true", help="Attach and poll only")
    args = parser.parse_args(argv)

    if args.launch:
        launch_chrome()
        print_manual_pause()
        return 0
    if not args.attach:
        launch_chrome()
        print_manual_pause()
        wait_for_enter()
    result = attach_and_poll()
    log(f"FAILURE_BOUNDARY={result.get('boundary')}")
    log(f"DIRECT_AUTHENTICATED_BROWSER_ACCESS={result.get('access')}")
    log(f"ZENROWS_REQUIRED_FOR_POLLING={result.get('zenrows_polling')}")
    return 0 if result.get("access") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
