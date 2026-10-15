"""Attach to an already-authenticated Chrome via CDP and call getMaclar.

Does not launch Chrome, inject cookies, or use ZenRows.
Does not modify production code.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from parser import extract_1x2, inspect_payload, unwrap_events, validate_against_raw, parse_event
from run import ENDPOINT, OUT, browser_fetch, log, print_http_block, write_json

CDP_URL = "http://127.0.0.1:9222"
EXPECTED_FIELDS = (
    "_id",
    "ev_sahibi",
    "deplasman",
    "lig_id",
    "code",
    "zaman",
    "oranlar",
    "type",
    "zs",
)


def connect_existing_chrome():
    from playwright.sync_api import sync_playwright

    log("Connecting to existing Chrome on port 9222...")
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    return playwright, browser


def list_pages(browser) -> list[dict]:
    rows = []
    for context in browser.contexts:
        for page in context.pages:
            url = page.url or ""
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""
            rows.append({"url": url, "title": title[:120], "page": page})
    return rows


def find_kolay90_page(rows: list[dict]):
    for row in rows:
        host = (urlsplit(row["url"]).hostname or "").lower()
        if host == "kolay90.com" or host.endswith(".kolay90.com"):
            return row
    return None


def count_1x2(events: list[dict]) -> int:
    return sum(1 for item in events if extract_1x2(item) is not None)


def mapping_checks(events: list[dict], limit: int = 8) -> list[dict]:
    checks = []
    for item in events:
        raw = extract_1x2(item)
        if raw is None:
            continue
        home = item.get("ev_sahibi")
        away = item.get("deplasman")
        parsed = parse_event(item)
        errors = validate_against_raw(item, parsed) if parsed is not None else []
        # Structural check even if the football filter rejects the event.
        structural_ok = (
            float(raw[0]) == float(item["oranlar"]["1"])
            and float(raw[1]) == float(item["oranlar"]["0"])
            and float(raw[2]) == float(item["oranlar"]["2"])
        )
        checks.append(
            {
                "home": home,
                "away": away,
                "raw_1_home": raw[0],
                "raw_0_draw": raw[1],
                "raw_2_away": raw[2],
                "keys_used": ["1", "0", "2"],
                "structural_ok": structural_ok,
                "parsed_as_football": parsed is not None,
                "parser_errors": errors,
            }
        )
        if len(checks) >= limit:
            break
    return checks


def field_presence(events: list[dict]) -> dict:
    counts = {key: 0 for key in EXPECTED_FIELDS}
    for item in events:
        for key in EXPECTED_FIELDS:
            if key in item:
                counts[key] += 1
    return counts


def slim_http(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if k != "payload"}


def navigate_same_tab_check(page) -> dict:
    """Diagnostic only if fetch fails. Does not print body."""
    try:
        response = page.goto(ENDPOINT, wait_until="domcontentloaded", timeout=45000)
        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        return {
            "status": response.status if response is not None else None,
            "content_type": response.headers.get("content-type") if response is not None else None,
            "title": title[:120],
            "url_host": urlsplit(page.url).hostname,
            "url_path": urlsplit(page.url).path,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def run() -> dict:
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "zenrows_used": False,
        "cookies_injected": False,
        "cdp_url": CDP_URL,
        "result": "CHROME_ATTACH_FAILED",
    }
    playwright = None
    browser = None
    try:
        playwright, browser = connect_existing_chrome()
    except Exception as exc:
        report["attach_error"] = f"{type(exc).__name__}: {exc}"
        report["chrome_start_command"] = (
            r'& "C:\Program Files\Google\Chrome\Application\chrome.exe" '
            r"--remote-debugging-port=9222 "
            r'--user-data-dir="experiments\kolay90_direct\chrome_profile"'
        )
        log("CHROME_ATTACH_FAILED")
        log("Start a dedicated Chrome, complete Cloudflare/login yourself, then re-run.")
        log(report["chrome_start_command"])
        return report

    try:
        rows = list_pages(browser)
        report["tabs"] = [{"url": r["url"], "title": r["title"]} for r in rows]
        log(f"Open tabs: {len(rows)}")
        for row in rows:
            log(f"  {row['title']!r}  {row['url']}")

        found = find_kolay90_page(rows)
        if found is None:
            report["result"] = "GETMACLAR_NOT_REACHED"
            report["kolay90_page_found"] = False
            log("No kolay90.com tab found. Open Kolay90 in this Chrome and re-run.")
            return report

        log("Authenticated Kolay90 page found.")
        report["kolay90_page_found"] = True
        report["page_url_host"] = urlsplit(found["url"]).hostname
        report["page_url_path"] = urlsplit(found["url"]).path
        report["page_title"] = found["title"]
        page = found["page"]

        first = browser_fetch(page)
        print()
        print_http_block("getMaclar from attached Chrome tab", first)
        report["first"] = slim_http(first)

        if first.get("status") != 200 or not first.get("json") or first.get("hata"):
            report["result"] = "DIRECT_BROWSER_SESSION_ACCESS_FAILED"
            log("DIRECT_BROWSER_SESSION_ACCESS = FAILED")
            log("Comparing same-tab navigation to getMaclar...")
            report["direct_navigation"] = navigate_same_tab_check(page)
            return report

        events = unwrap_events(first.get("payload"))
        inventory = inspect_payload(first.get("payload"))
        ones = count_1x2(events)
        checks = mapping_checks(events)
        report["inventory"] = inventory
        report["event_count"] = len(events)
        report["one_x_two_count"] = ones
        report["field_presence"] = field_presence(events)
        report["mapping_checks"] = checks
        mapping_ok = bool(checks) and all(c["structural_ok"] for c in checks)

        log("DIRECT_BROWSER_ACCESS = SUCCESS")
        log(f"Event count: {len(events)}")
        log(f"1X2 event count: {ones}")
        log(f"Odds mapping 1=HOME 0=DRAW 2=AWAY: {'CONFIRMED' if mapping_ok else 'INCOMPLETE'}")
        for row in checks[:6]:
            print(
                f"  {row['home']} vs {row['away']} | "
                f"1/HOME={row['raw_1_home']} 0/DRAW={row['raw_0_draw']} "
                f"2/AWAY={row['raw_2_away']} | OK={row['structural_ok']}"
            )

        time.sleep(10)
        second = browser_fetch(page)
        report["second"] = slim_http(second)
        log(
            f"FIRST REQUEST: status={first.get('status')} events={len(events)}"
        )
        log(
            f"SECOND REQUEST: status={second.get('status')} "
            f"events={second.get('event_count')}"
        )

        polls = [slim_http(first), slim_http(second)]
        for index in range(3):
            if index:
                time.sleep(8)
            row = browser_fetch(page)
            events_n = unwrap_events(row.get("payload")) if row.get("json") else []
            polls.append(
                {
                    **slim_http(row),
                    "poll_n": index + 1,
                    "one_x_two_count": count_1x2(events_n),
                }
            )
            log(
                f"Poll {index + 1}: status={row.get('status')} "
                f"events={row.get('event_count')} "
                f"1x2={count_1x2(events_n)} bytes={row.get('bytes')}"
            )
        report["polls"] = polls
        persistent = (
            first.get("status") == 200
            and second.get("status") == 200
            and all(p.get("status") == 200 and p.get("json") for p in polls[-3:])
        )
        report["persistent"] = persistent
        if persistent:
            log("PERSISTENT_BROWSER_SESSION = SUCCESS")
        report["result"] = "DIRECT_BROWSER_SESSION_ACCESS_SUCCESS"
        report["mapping_confirmed"] = mapping_ok
        return report
    finally:
        log("Leaving the attached Chrome session open.")
        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass


def print_final(report: dict) -> None:
    print()
    print("### Result")
    print(report.get("result"))
    print()
    print("### Evidence")
    print(f"- Chrome CDP attachment: {'YES' if report.get('tabs') is not None else 'NO'}")
    print(f"- Authenticated Kolay90 page found: {'YES' if report.get('kolay90_page_found') else 'NO'}")
    print("- Manual Cloudflare completed: USER-ESTABLISHED (not automated)")
    first = report.get("first") or {}
    authenticated = bool(first.get("status") == 200 and first.get("json") and not first.get("hata"))
    print(f"- Direct getMaclar from same browser: {'YES' if authenticated else 'NO'}")
    if first.get("hata"):
        print("- getMaclar JSON was the unauthenticated hata payload (login required in this Chrome)")
    print(f"- HTTP status: {first.get('status')}")
    print(f"- JSON: {'YES' if first.get('json') else 'NO'}")
    print(f"- Event count: {report.get('event_count')}")
    print(f"- 1X2 event count: {report.get('one_x_two_count')}")
    print(f"- Second request: {(report.get('second') or {}).get('status')}")
    polls = report.get("polls") or []
    third = polls[-1] if len(polls) >= 3 else {}
    print(f"- Third request: {third.get('status')}")
    print(f"- Persistent session: {'YES' if report.get('persistent') else 'NO'}")
    print()
    print("### Odds mapping")
    if report.get("mapping_confirmed"):
        print("1 = HOME, 0 = DRAW, 2 = AWAY confirmed on multiple events with those keys.")
    else:
        print("Not confirmed on multiple events (missing 1/0/2 keys or attach failed).")
    write_json("attach_cdp_report.json", json.loads(json.dumps(report, default=str)))
    log(f"Sanitized report: {OUT / 'attach_cdp_report.json'}")


def main() -> int:
    report = run()
    print_final(report)
    return 0 if report.get("result") == "DIRECT_BROWSER_SESSION_ACCESS_SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
