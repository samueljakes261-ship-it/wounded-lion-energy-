"""Isolated kolay90 persistent-browser + direct HTTP experiment.

Does not import or modify production parsers, collector, run_engine,
ZenRows, BetKanyon, Orbit, or OnWin.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from parser import (
    extract_1x2,
    inspect_payload,
    parse_event,
    reject_reason,
    unwrap_events,
    validate_against_raw,
)

ENDPOINT = "https://kolay90.com/service/getMaclar"
HOME = "https://kolay90.com/"
PROFILE = HERE / "browser_profile"
OUT = HERE / "output"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)


def log(message: str = "") -> None:
    print(f"[KOLAY90 EXPERIMENT] {message}" if message else "[KOLAY90 EXPERIMENT]")


def write_json(name: str, payload) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summarize_cookies(cookies: list[dict]) -> dict:
    names = sorted({c.get("name") for c in cookies if c.get("name")})
    domains = sorted({c.get("domain") or "" for c in cookies})
    return {
        "count": len(cookies),
        "names": names,
        "domains": domains,
        "with_expiry": sum(1 for c in cookies if c.get("expires")),
        "bet_cms": "bet_cms" in names,
        "cf_clearance": "cf_clearance" in names,
    }


def print_cookie_report(info: dict) -> None:
    log(f"Cookies detected: {info['count']}")
    log(f"Cookie names: {', '.join(info['names']) or '(none)'}")
    log(f"Cookie domains: {', '.join(info['domains']) or '(none)'}")
    log(f"Cookies with expiry: {info['with_expiry']}")
    log(f"bet_cms: {'PRESENT' if info['bet_cms'] else 'ABSENT'}")
    log(f"cf_clearance: {'PRESENT' if info['cf_clearance'] else 'ABSENT'}")


def looks_like_unauth(payload) -> bool:
    return isinstance(payload, dict) and payload.get("hata") is True


def summarize_body(status: int, content_type: str | None, raw: bytes) -> dict:
    text = raw.decode("utf-8", "replace") if raw else ""
    json_ok = False
    payload = None
    if text and text.lstrip()[:1] in "{[":
        try:
            payload = json.loads(text)
            json_ok = True
        except json.JSONDecodeError:
            payload = None
    events = unwrap_events(payload) if json_ok else []
    return {
        "status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "json": json_ok,
        "hata": looks_like_unauth(payload) if json_ok else None,
        "authenticated": bool(json_ok and not looks_like_unauth(payload) and events),
        "event_count": len(events),
        "payload": payload,
        "etag": None,
    }


def browser_fetch(page) -> dict:
    result = page.evaluate(
        """async (url) => {
            const started = Date.now();
            const response = await fetch(url, {
                method: 'GET',
                credentials: 'include',
                headers: {
                    'accept': 'application/json, text/plain, */*',
                    'x-requested-with': 'XMLHttpRequest',
                },
            });
            const text = await response.text();
            return {
                status: response.status,
                content_type: response.headers.get('content-type'),
                etag: response.headers.get('etag'),
                cache_control: response.headers.get('cache-control'),
                bytes: new TextEncoder().encode(text).length,
                text: text,
                latency_ms: Date.now() - started,
            };
        }""",
        ENDPOINT,
    )
    raw = (result.get("text") or "").encode("utf-8")
    summary = summarize_body(result.get("status"), result.get("content_type"), raw)
    summary["etag"] = result.get("etag")
    summary["cache_control"] = result.get("cache_control")
    return summary


def cookie_jar(cookies: list[dict]) -> requests.cookies.RequestsCookieJar:
    jar = requests.cookies.RequestsCookieJar()
    for cookie in cookies:
        try:
            jar.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path") or "/",
            )
        except Exception:
            continue
    return jar


def direct_request(cookies: list[dict], extra_headers: dict | None = None, etag: str | None = None) -> dict:
    session = requests.Session()
    session.trust_env = False
    session.cookies = cookie_jar(cookies)
    headers = dict(extra_headers or {})
    if etag:
        headers["If-None-Match"] = etag
    started = time.perf_counter()
    response = session.get(ENDPOINT, headers=headers, timeout=45)
    summary = summarize_body(
        response.status_code,
        response.headers.get("content-type"),
        response.content or b"",
    )
    summary["etag"] = response.headers.get("etag")
    summary["cache_control"] = response.headers.get("cache-control")
    summary["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return summary


def print_http_block(title: str, summary: dict) -> None:
    log(title)
    log(f"Status: {summary.get('status')}")
    log(f"Content-Type: {summary.get('content_type')}")
    log(f"Response bytes: {summary.get('bytes')}")
    log(f"JSON: {'YES' if summary.get('json') else 'NO'}")
    if summary.get("hata") is True:
        log("Authenticated response: NO (hata=true)")
    else:
        log(f"Authenticated response: {'YES' if summary.get('authenticated') else 'NO'}")
    if summary.get("event_count") is not None:
        log(f"Event objects: {summary.get('event_count')}")


def wait_for_manual_ready() -> None:
    log("Waiting for manual Cloudflare/login/session establishment.")
    ready = OUT / "READY"
    ready.unlink(missing_ok=True)
    if sys.stdin.isatty():
        log("When the authenticated site is ready, press ENTER.")
        try:
            input()
            return
        except EOFError:
            pass
    log(f"When the authenticated site is ready, create this empty file: {ready}")
    while not ready.exists():
        time.sleep(1)
    ready.unlink(missing_ok=True)
    log("Ready signal received.")


def launch_persistent():
    from playwright.sync_api import sync_playwright

    log("Launching persistent browser...")
    PROFILE.mkdir(parents=True, exist_ok=True)
    log(f"Browser profile: experiments/kolay90_direct/browser_profile/")
    playwright = sync_playwright().start()
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
            locale="tr-TR",
            user_agent=USER_AGENT,
        )
    except Exception:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            viewport={"width": 1400, "height": 900},
            locale="tr-TR",
            user_agent=USER_AGENT,
        )
    page = context.pages[0] if context.pages else context.new_page()
    return playwright, context, page


def page_signals(page) -> dict:
    title = ""
    url = ""
    try:
        title = page.title()
        url = page.url
    except Exception:
        pass
    interstitial = "just a moment" in title.lower() or "attention required" in title.lower()
    return {
        "title": title[:120],
        "host": urlparse(url).hostname,
        "path": urlparse(url).path,
        "cloudflare_challenge": interstitial,
    }


def football_parse_report(payload) -> dict:
    inventory = inspect_payload(payload)
    events = unwrap_events(payload)
    parsed = []
    checks = []
    failures = 0
    rejected = Counter()
    for item in events:
        reason = reject_reason(item)
        if reason:
            rejected[reason] += 1
        match = parse_event(item)
        if match is None:
            continue
        parsed.append(match)
        errors = validate_against_raw(item, match)
        raw = extract_1x2(item)
        row = {
            "home": match.home_team,
            "away": match.away_team,
            "raw_home": raw[0] if raw else None,
            "raw_draw": raw[1] if raw else None,
            "raw_away": raw[2] if raw else None,
            "parsed_home": match.home_back,
            "parsed_draw": match.draw_back,
            "parsed_away": match.away_back,
            "match": "PASS" if not errors else "FAIL",
            "errors": errors,
        }
        checks.append(row)
        if errors:
            failures += 1
    return {
        "inventory": inventory,
        "rejected": dict(rejected),
        "football_1x2": len(parsed),
        "validation_failures": failures,
        "validation": "FAIL" if failures else ("PASS" if parsed else "FAIL"),
        "parsed": parsed,
        "checks": checks,
    }


def print_parser_samples(report: dict) -> None:
    log("PARSER")
    if report["inventory"].get("football_discriminator"):
        log(f"Football discriminator: {report['inventory']['football_discriminator']}")
    if report["inventory"].get("sport_field_values"):
        log(f"Sport field values: {report['inventory']['sport_field_values']}")
    if report["inventory"].get("type_values"):
        log(f"type values: {report['inventory']['type_values']}")
    log(f"Football 1X2 events: {report['football_1x2']}")
    if report.get("rejected"):
        log(f"Rejected events: {report['rejected']}")
    for match in report["parsed"][:8]:
        print()
        print(f"[KOLAY90 PARSER]")
        print()
        print(f"{match.home_team} vs {match.away_team}")
        print(f"HOME: {match.home_back}")
        print(f"DRAW: {match.draw_back}")
        print(f"AWAY: {match.away_back}")
    print()
    log("Accuracy check (up to 10 events)")
    for row in report["checks"][:10]:
        print(
            f"  {row['home']} vs {row['away']} | "
            f"raw HOME={row['raw_home']} parsed={row['parsed_home']} | "
            f"raw DRAW={row['raw_draw']} parsed={row['parsed_draw']} | "
            f"raw AWAY={row['raw_away']} parsed={row['parsed_away']} | "
            f"MATCH = {row['match']}"
        )
        if row["errors"]:
            print(f"    FAIL {row['errors']}")
            raise SystemExit("Parser accuracy check failed.")


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "zenrows_used": False,
        "endpoint": ENDPOINT,
    }
    playwright, context, page = launch_persistent()
    try:
        page.goto(HOME, wait_until="domcontentloaded", timeout=120000)
        wait_for_manual_ready()
        cookies = context.cookies()
        cookie_info = summarize_cookies(cookies)
        print_cookie_report(cookie_info)
        report["cookies"] = cookie_info
        report["page"] = page_signals(page)
        report["login"] = "UNKNOWN"
        report["cloudflare"] = (
            "FAILED" if report["page"]["cloudflare_challenge"] else "MANUAL CLEARANCE SUCCESS"
        )

        browser_summary = browser_fetch(page)
        print()
        print_http_block("Browser-context endpoint test", browser_summary)
        report["browser_getmaclar"] = {
            k: v for k, v in browser_summary.items() if k != "payload"
        }
        if browser_summary.get("payload") is not None:
            report["payload_inventory"] = inspect_payload(browser_summary["payload"])

        if not browser_summary.get("json") or browser_summary.get("hata"):
            report["direct_getmaclar"] = {"ok": False, "reason": "browser-context request did not return match JSON"}
            report["conclusion"] = (
                "No: the authenticated browser context did not obtain getMaclar JSON, "
                "so direct HTTP was not attempted."
            )
            return report

        cookies = context.cookies()
        variants = [
            ("cookies_only", {}),
            ("cookies_user_agent", {"User-Agent": USER_AGENT}),
            (
                "cookies_ua_xhr",
                {
                    "User-Agent": USER_AGENT,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*",
                },
            ),
            (
                "cookies_ua_xhr_origin",
                {
                    "User-Agent": USER_AGENT,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://kolay90.com",
                    "Referer": "https://kolay90.com/",
                },
            ),
        ]
        variant_results = []
        winning = None
        winning_headers = None
        for name, headers in variants:
            summary = direct_request(cookies, headers)
            slim = {k: v for k, v in summary.items() if k != "payload"}
            slim["variant"] = name
            variant_results.append(slim)
            log(f"Direct HTTP variant {name}: status={slim['status']} json={slim['json']} auth={slim['authenticated']}")
            if summary.get("authenticated"):
                winning = summary
                winning_headers = headers
                break
        report["direct_variants"] = variant_results
        if winning is None:
            last = variant_results[-1] if variant_results else {}
            print()
            print_http_block("Direct HTTP test", last)
            report["direct_getmaclar"] = {"ok": False, "variants": variant_results}
            report["conclusion"] = (
                "No: browser-context getMaclar succeeded, but standalone HTTP "
                "did not return the match JSON with the current cookie jar."
            )
            return report

        print()
        print_http_block("Direct HTTP test", winning)
        report["direct_getmaclar"] = {
            "ok": True,
            "winning_variant": variant_results[-1]["variant"],
            **{k: v for k, v in winning.items() if k != "payload"},
        }

        etag = winning.get("etag")
        etag_fresh = direct_request(cookies, winning_headers)
        etag_cached = direct_request(cookies, winning_headers, etag=etag) if etag else None
        report["etag"] = {
            "seen_etag": etag,
            "cache_control": winning.get("cache_control"),
            "fresh_without_if_none_match": {
                k: etag_fresh.get(k)
                for k in ("status", "bytes", "event_count", "etag")
            },
            "with_if_none_match": (
                {k: etag_cached.get(k) for k in ("status", "bytes", "event_count", "etag")}
                if etag_cached
                else None
            ),
        }
        log("ETag/cache")
        log(f"etag present: {'YES' if etag else 'NO'}")
        log(f"fresh request status: {etag_fresh.get('status')} bytes={etag_fresh.get('bytes')}")
        if etag_cached:
            log(f"If-None-Match request status: {etag_cached.get('status')} bytes={etag_cached.get('bytes')}")

        repeats = []
        payload_for_parse = winning.get("payload")
        for index in range(3):
            if index:
                time.sleep(10)
            row = direct_request(cookies, winning_headers)
            parse_info = inspect_payload(row.get("payload"))
            parsed = football_parse_report(row.get("payload")) if row.get("json") else None
            repeats.append(
                {
                    "n": index + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": row.get("status"),
                    "bytes": row.get("bytes"),
                    "event_count": row.get("event_count"),
                    "etag": row.get("etag"),
                    "football_1x2": parsed["football_1x2"] if parsed else 0,
                    "authenticated": row.get("authenticated"),
                }
            )
            log(
                f"Repeat {index + 1}: status={row.get('status')} bytes={row.get('bytes')} "
                f"events={row.get('event_count')} football_1x2="
                f"{parsed['football_1x2'] if parsed else 0}"
            )
            if row.get("authenticated"):
                payload_for_parse = row.get("payload")
        report["repeats"] = repeats

        parse_report = football_parse_report(payload_for_parse)
        print_parser_samples(parse_report)
        report["parse"] = {
            "inventory": parse_report["inventory"],
            "football_1x2": parse_report["football_1x2"],
            "validation": parse_report["validation"],
            "validation_failures": parse_report["validation_failures"],
            "rejected": parse_report.get("rejected"),
            "sample": [
                {
                    "home": m.home_team,
                    "away": m.away_team,
                    "home_back": m.home_back,
                    "draw_back": m.draw_back,
                    "away_back": m.away_back,
                }
                for m in parse_report["parsed"][:10]
            ],
        }
        write_json(
            "parsed_sample.json",
            report["parse"]["sample"],
        )

        log("Restart test")
        context.close()
        playwright.stop()
        playwright, context, page = launch_persistent()
        page.goto(HOME, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(4000)
        restart_page = page_signals(page)
        restart_cookies = summarize_cookies(context.cookies())
        restart_http = None
        if restart_cookies["bet_cms"] or restart_cookies["cf_clearance"]:
            restart_http = direct_request(
                context.cookies(),
                winning_headers or {"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
            )
        report["restart"] = {
            "page": restart_page,
            "cookies": restart_cookies,
            "authenticated_http": bool(restart_http and restart_http.get("authenticated")),
            "cloudflare_challenge": restart_page["cloudflare_challenge"],
        }
        log(f"Authenticated after restart: {'YES' if report['restart']['authenticated_http'] else 'NO'}")
        log(f"Cloudflare challenge after restart: {'YES' if restart_page['cloudflare_challenge'] else 'NO'}")
        log(
            "Login required after restart: "
            f"{'UNKNOWN' if report['restart']['authenticated_http'] else 'LIKELY'}"
        )
        report["conclusion"] = (
            "Yes: a legitimate persistent Chrome session can mint cookies that "
            f"direct HTTP reuses ({report['direct_getmaclar'].get('winning_variant')})."
            if report["direct_getmaclar"].get("ok")
            else "No: see failure above."
        )
        return report
    finally:
        try:
            context.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass


def print_final(report: dict) -> None:
    cookies = report.get("cookies") or {}
    browser = report.get("browser_getmaclar") or {}
    direct = report.get("direct_getmaclar") or {}
    parse = report.get("parse") or {}
    restart = report.get("restart") or {}
    print()
    print("### KOLAY90 DIRECT ACCESS EXPERIMENT")
    print()
    print(f"Session establishment: {'SUCCESS' if cookies.get('count') else 'FAILED'}")
    print(f"Cloudflare: {report.get('cloudflare') or 'UNKNOWN'}")
    print(f"Login: {report.get('login') or 'UNKNOWN'}")
    print("Persistent browser: SUCCESS")
    print(f"bet_cms present: {'YES' if cookies.get('bet_cms') else 'NO'}")
    print(f"cf_clearance present: {'YES' if cookies.get('cf_clearance') else 'NO'}")
    print(f"Browser-context getMaclar: {'SUCCESS' if browser.get('authenticated') else 'FAILED'}")
    print(f"Direct HTTP getMaclar: {'SUCCESS' if direct.get('ok') else 'FAILED'}")
    print("ZenRows used: NO")
    repeats = report.get("repeats") or []
    print(
        "Fresh repeated HTTP requests: "
        f"{'SUCCESS' if repeats and all(r.get('authenticated') for r in repeats) else 'FAILED'}"
    )
    print(
        "Session survives browser restart: "
        f"{'YES' if restart.get('authenticated_http') else 'NO'}"
    )
    inventory = parse.get("inventory") or report.get("payload_inventory") or {}
    print(f"Football events discovered: {inventory.get('event_count', 'n/a')}")
    print(f"Football 1X2 events: {parse.get('football_1x2', 0)}")
    print(f"Successfully parsed MatchOdds: {parse.get('football_1x2', 0)}")
    print(f"Raw-vs-parsed validation: {parse.get('validation', 'FAIL')}")
    print("ETag/cache behavior:")
    print(json.dumps(report.get("etag") or {}, indent=2))
    print()
    print("### CONCLUSION")
    print(report.get("conclusion"))
    write_json("report.json", json.loads(json.dumps(report, default=str)))
    log(f"Sanitized report: {OUT / 'report.json'}")


def main() -> int:
    report = run()
    print_final(report)
    return 0 if (report.get("direct_getmaclar") or {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
