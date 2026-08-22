"""Isolated OnWin get_main_line direct-access experiment.

Does NOT import or modify parsers/onwin, collector, run_engine, or
ZenRows. Captured session tokens are held in memory only and are
redacted in every log and on-disk report.

Question: after a normal browser session on OnWin, can get_main_line
be obtained without routing through ZenRows?
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "output"

# Same public sportsbook path the production feed uses. Domain numbers
# rotate; override with ONWIN_EXPERIMENT_PAGE if this host has moved.
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
TARGET = "get_main_line.erisgaming"
GAP_TARGET = "get_main_line_gap.erisgaming"

# Diagnostic-only football sport id, copied from public payload shape.
# Production parser is NOT imported.
FOOTBALL_SPORT_ID = "d6934640-cf1d-11e9-864b-0242ac13000a"

SENSITIVE_HEADER_NAMES = (
    "x-token",
    "x-message-metadata",
    "cookie",
    "authorization",
    "set-cookie",
)

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

BROWSER_MANAGED = {"cookie", "origin", "referer", "host"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mkdir_out() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR


def _redact_secret(value: str | None, prefix_len: int = 5) -> dict:
    if not value:
        return {"present": False, "length": 0, "prefix": None}
    text = str(value)
    shown = text[:prefix_len] if len(text) >= prefix_len else "(short)"
    return {
        "present": True,
        "length": len(text),
        "prefix": f"{shown}...",
    }


def _header_lookup(headers: dict, name: str) -> str | None:
    want = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == want:
            return value
    return None


def print_secret_line(label: str, value: str | None) -> None:
    info = _redact_secret(value)
    if not info["present"]:
        print(f"  {label}: ABSENT")
        return
    print(
        f"  {label}: PRESENT length={info['length']} prefix={info['prefix']}"
    )


def redact_headers(headers: dict) -> dict:
    out = {}
    for key, value in (headers or {}).items():
        if str(key).lower() in SENSITIVE_HEADER_NAMES:
            out[key] = _redact_secret(value)
        else:
            out[key] = value
    return out


def looks_like_interstitial(title: str | None, host: str | None) -> bool:
    text = f"{title or ''} {host or ''}".lower()
    return "just a moment" in text or "attention required" in text


def looks_like_challenge(status: int | None, content_type: str | None, text: str | None) -> bool:
    blob = f"{content_type or ''} {(text or '')[:800]}".lower()
    if status in (401, 403, 429, 503):
        if any(tok in blob for tok in ("cloudflare", "cf-ray", "captcha", "challenge", "attention required")):
            return True
    return any(tok in blob for tok in ("cloudflare", "cf-ray", "just a moment", "attention required"))


def count_football_events(payload) -> tuple[int | None, bool]:
    """Heuristic event count. Does not use the production parser.

    Known snapshot shape: sports[football_id].categories.*.tournaments.*.events
    """
    data = payload
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None, False
    inner = data.get("result")
    if isinstance(inner, (dict, list)) and "sports" not in data:
        return count_football_events(inner)
    sports = data.get("sports")
    if not isinstance(sports, dict):
        return None, "sports" in data
    football = sports.get(FOOTBALL_SPORT_ID)
    contains = FOOTBALL_SPORT_ID in sports
    if not isinstance(football, dict):
        return (0 if contains else None), contains
    events = 0
    categories = football.get("categories") or {}
    if isinstance(categories, dict):
        for category in categories.values():
            if not isinstance(category, dict):
                continue
            tournaments = category.get("tournaments") or {}
            if not isinstance(tournaments, dict):
                continue
            for tournament in tournaments.values():
                if not isinstance(tournament, dict):
                    continue
                ev = tournament.get("events")
                if isinstance(ev, dict):
                    events += len(ev)
                elif isinstance(ev, list):
                    events += len(ev)
    return events, contains or events > 0


def summarize_json_body(body: bytes | str | None) -> dict:
    summary = {
        "appears_json": False,
        "top_level_type": None,
        "top_level_keys": None,
        "event_count": None,
        "contains_expected_structure": False,
        "parse_error": None,
    }
    if body is None:
        return summary
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            summary["parse_error"] = "not_utf8"
            return summary
    else:
        text = body
    text = text.strip()
    if not text or text[:1] not in "{[":
        return summary
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        summary["parse_error"] = type(exc).__name__
        return summary
    summary["appears_json"] = True
    summary["top_level_type"] = type(parsed).__name__
    if isinstance(parsed, dict):
        summary["top_level_keys"] = list(parsed.keys())[:40]
    elif isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        summary["top_level_keys"] = list(parsed[0].keys())[:40]
    event_count, expected = count_football_events(parsed)
    summary["event_count"] = event_count
    summary["contains_expected_structure"] = bool(expected or (isinstance(parsed, dict) and "sports" in parsed))
    return summary


def classify(report: dict) -> str:
    browser = report.get("browser") or {}
    observed = report.get("observed_request") or {}
    test_a = report.get("test_a_browser_fetch") or {}
    test_b = report.get("test_b_required_state") or {}
    test_c = report.get("test_c_standalone_http") or {}

    page_loaded = bool(browser.get("page_loaded"))
    observed_ok = observed.get("observed") is True
    browser_status = observed.get("response_status")
    a_status = test_a.get("status")
    c_status = test_c.get("status")
    a_ok = a_status == 200 and bool(test_a.get("appears_json"))
    c_ok = c_status == 200 and bool(test_c.get("appears_json"))

    if not page_loaded and not observed_ok:
        if browser.get("error"):
            return "INCONCLUSIVE"
        return "DIRECT_ACCESS_REQUIRES_ZENROWS"

    if not observed_ok:
        return "DIRECT_ACCESS_REQUIRES_ZENROWS"

    if browser_status not in (None, 200) and not a_ok:
        if browser_status in (401, 403):
            return "DIRECT_ACCESS_REQUIRES_ZENROWS"
        return "INCONCLUSIVE"

    token_needed = False
    variants = test_b.get("variants") or []
    full_ok = any(v.get("name") == "full" and v.get("status") == 200 for v in variants)
    no_token = next((v for v in variants if v.get("name") == "omit_x-token"), None)
    no_meta = next((v for v in variants if v.get("name") == "omit_x-message-metadata"), None)
    if full_ok:
        if no_token and no_token.get("status") != 200:
            token_needed = True
        if no_meta and no_meta.get("status") != 200:
            token_needed = True

    if a_ok and c_ok:
        if token_needed:
            return "DIRECT_ACCESS_REQUIRES_SESSION_METADATA"
        return "DIRECT_ACCESS_WORKS"
    if a_ok and not c_ok:
        if token_needed:
            return "DIRECT_ACCESS_REQUIRES_SESSION_METADATA"
        return "DIRECT_ACCESS_WORKS_ONLY_INSIDE_BROWSER"
    if observed.get("response_status") == 200 and not a_ok:
        return "INCONCLUSIVE"
    return "DIRECT_ACCESS_REQUIRES_ZENROWS"


def situation_note(label: str, report: dict | None = None) -> str:
    report = report or {}
    browser = report.get("browser") or {}
    failure = report.get("failure") or ""
    interstitial = bool(browser.get("cloudflare_interstitial"))
    if label == "DIRECT_ACCESS_REQUIRES_ZENROWS" and interstitial:
        return (
            "C: a normal local Chromium session was held at a Cloudflare "
            "'Just a moment...' interstitial. get_main_line was never requested. "
            "This does not prove the API itself only works through ZenRows (B); "
            "it shows this browser did not establish the session the production "
            "ZenRows path apparently does."
        )
    if label == "DIRECT_ACCESS_REQUIRES_ZENROWS" and "never requested" in failure:
        return (
            "C: OnWin loaded something in the local browser, but get_main_line "
            "was never requested, so a direct API replay could not be attempted."
        )
    return {
        "DIRECT_ACCESS_WORKS": (
            "A: the API is accessible directly once a valid browser session exists "
            "(in-page fetch and standalone HTTP both succeeded)."
        ),
        "DIRECT_ACCESS_WORKS_ONLY_INSIDE_BROWSER": (
            "A-ish / browser-bound: the established page can call the API, but a "
            "standalone HTTP client could not reproduce it. Not evidence that ZenRows "
            "is uniquely required — only that browser context mattered in this run."
        ),
        "DIRECT_ACCESS_REQUIRES_SESSION_METADATA": (
            "D: the API requires dynamically generated session metadata "
            "(x-token and/or x-message-metadata) captured from the live page."
        ),
        "DIRECT_ACCESS_REQUIRES_ZENROWS": (
            "B or C: a normal local browser session did not yield a usable "
            "get_main_line response without ZenRows."
        ),
        "INCONCLUSIVE": (
            "Not enough evidence to choose A/B/C/D. See failure diagnostics."
        ),
    }.get(label, "Unknown classification.")


def _is_target_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    if GAP_TARGET in lower:
        return False
    return TARGET in lower


def _safe_url(url: str) -> dict:
    parts = urlsplit(url or "")
    return {
        "scheme": parts.scheme,
        "host": parts.hostname,
        "path": parts.path,
        "has_query": bool(parts.query),
        "url_no_query": f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.path,
    }


def capture_from_request(request) -> dict:
    try:
        headers = request.all_headers()
    except Exception:
        headers = dict(request.headers or {})
    post_data = None
    try:
        post_data = request.post_data
    except Exception:
        post_data = None
    return {
        "url": request.url,
        "method": request.method,
        "headers": headers,
        "post_data": post_data,
        "resource_type": getattr(request, "resource_type", None),
    }


def summarize_observed(req: dict, response) -> dict:
    headers = req.get("headers") or {}
    token = _header_lookup(headers, "x-token")
    metadata = _header_lookup(headers, "x-message-metadata")
    origin = _header_lookup(headers, "origin")
    content_type = _header_lookup(headers, "content-type")
    cookie = _header_lookup(headers, "cookie")
    status = None
    resp_ct = None
    resp_bytes = None
    body_summary = summarize_json_body(None)
    challenge = False
    if response is not None:
        status = response.status
        resp_ct = response.headers.get("content-type")
        try:
            body = response.body()
            resp_bytes = len(body) if body is not None else 0
            body_summary = summarize_json_body(body)
            preview = ""
            try:
                preview = body[:400].decode("utf-8", "replace") if body else ""
            except Exception:
                preview = ""
            challenge = looks_like_challenge(status, resp_ct, preview)
        except Exception as exc:
            body_summary["parse_error"] = f"{type(exc).__name__}: {exc}"
    header_names = sorted(str(k).lower() for k in headers)
    return {
        "observed": True,
        "url": _safe_url(req.get("url") or ""),
        "method": req.get("method"),
        "content_type": content_type,
        "origin": origin,
        "header_names": header_names,
        "x-token": _redact_secret(token),
        "x-message-metadata": _redact_secret(metadata),
        "cookies_on_request": bool(cookie),
        "response_status": status,
        "response_content_type": resp_ct,
        "response_bytes": resp_bytes,
        "looks_like_challenge": challenge,
        **body_summary,
    }


def browser_fetch(page, url: str, method: str, headers: dict, post_data: str | None, omit: set[str] | None, credentials: str):
    omit = {n.lower() for n in (omit or set())}
    send_headers = {}
    for key, value in (headers or {}).items():
        low = str(key).lower()
        if low in HOP_BY_HOP or low in BROWSER_MANAGED or low in omit:
            continue
        if value is None:
            continue
        send_headers[key] = value
    payload = {
        "url": url,
        "method": method or "POST",
        "headers": send_headers,
        "body": post_data,
        "credentials": credentials,
    }
    return page.evaluate(
        """async (args) => {
            const footballId = 'd6934640-cf1d-11e9-864b-0242ac13000a';
            const countEvents = (parsed) => {
                try {
                    const root = Array.isArray(parsed) ? parsed[0] : parsed;
                    const sports = root && root.sports;
                    if (!sports) return null;
                    const football = sports[footballId];
                    if (!football) return 0;
                    let n = 0;
                    const cats = football.categories || {};
                    for (const c of Object.values(cats)) {
                        const tours = (c && c.tournaments) || {};
                        for (const t of Object.values(tours)) {
                            const ev = (t && t.events) || {};
                            n += Array.isArray(ev) ? ev.length : Object.keys(ev).length;
                        }
                    }
                    return n;
                } catch (e) { return null; }
            };
            const init = {
                method: args.method,
                credentials: args.credentials,
                headers: args.headers || {},
            };
            if (args.body != null && args.method && args.method.toUpperCase() !== 'GET') {
                init.body = args.body;
            }
            const started = Date.now();
            try {
                const response = await fetch(args.url, init);
                const text = await response.text();
                let keys = null;
                let appearsJson = false;
                let topType = null;
                let eventCount = null;
                let containsExpected = false;
                try {
                    const parsed = JSON.parse(text);
                    appearsJson = true;
                    topType = Array.isArray(parsed) ? 'list' : typeof parsed;
                    const root = Array.isArray(parsed) ? parsed[0] : parsed;
                    if (root && typeof root === 'object' && !Array.isArray(root)) {
                        keys = Object.keys(root).slice(0, 40);
                        containsExpected = Object.prototype.hasOwnProperty.call(root, 'sports');
                    }
                    eventCount = countEvents(parsed);
                } catch (e) {}
                return {
                    status: response.status,
                    content_type: response.headers.get('content-type'),
                    response_bytes: new TextEncoder().encode(text).length,
                    appears_json: appearsJson,
                    top_level_type: topType,
                    top_level_keys: keys,
                    event_count: eventCount,
                    contains_expected_structure: containsExpected,
                    latency_ms: Date.now() - started,
                    preview: text.slice(0, 180),
                };
            } catch (err) {
                return {
                    status: null,
                    error: String(err),
                    latency_ms: Date.now() - started,
                };
            }
        }""",
        payload,
    )


def slim_fetch_result(raw: dict) -> dict:
    result = dict(raw or {})
    preview = result.pop("preview", "") or ""
    result["looks_like_challenge"] = looks_like_challenge(
        result.get("status"), result.get("content_type"), preview
    )
    return result


def standalone_http(url: str, method: str, headers: dict, post_data: str | None, cookies: list[dict]) -> dict:
    session = requests.Session()
    session.trust_env = False
    for cookie in cookies:
        try:
            session.cookies.set(
                cookie.get("name"),
                cookie.get("value"),
                domain=cookie.get("domain"),
                path=cookie.get("path") or "/",
            )
        except Exception:
            continue
    send_headers = {}
    for key, value in (headers or {}).items():
        low = str(key).lower()
        if low in HOP_BY_HOP or low == "cookie":
            continue
        send_headers[key] = value
    started = time.perf_counter()
    try:
        response = session.request(
            method or "POST",
            url,
            headers=send_headers,
            data=post_data,
            timeout=60,
        )
    except Exception as exc:
        return {
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "cookie_count": len(cookies),
        }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = response.content or b""
    summary = summarize_json_body(body)
    preview = ""
    try:
        preview = body[:400].decode("utf-8", "replace")
    except Exception:
        preview = ""
    return {
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "response_bytes": len(body),
        "latency_ms": elapsed_ms,
        "cookie_count": len(cookies),
        "looks_like_challenge": looks_like_challenge(response.status_code, response.headers.get("content-type"), preview),
        **summary,
    }


def required_state_notes(test_b: dict, observed: dict) -> dict:
    variants = {v.get("name"): v for v in (test_b.get("variants") or [])}
    def ok(name: str) -> bool | None:
        row = variants.get(name)
        if not row:
            return None
        return row.get("status") == 200 and bool(row.get("appears_json") or row.get("contains_expected_structure"))

    full = ok("full")
    return {
        "cookies": {
            "present_on_observed_request": bool(observed.get("cookies_on_request")),
            "required": (ok("credentials_omit") is False) if full else None,
        },
        "x-token": {
            "present": bool((observed.get("x-token") or {}).get("present")),
            "required": (ok("omit_x-token") is False) if full else None,
        },
        "x-message-metadata": {
            "present": bool((observed.get("x-message-metadata") or {}).get("present")),
            "required": (ok("omit_x-message-metadata") is False) if full else None,
        },
        "origin": {
            "present": bool(observed.get("origin")),
            "value": observed.get("origin"),
            "note": "Browser fetch sends Origin automatically; standalone HTTP sets it from the captured request.",
        },
        "browser_context": {
            "in_page_fetch_attempted": "full" in variants or bool(test_b),
        },
    }


def run() -> dict:
    page_url = os.environ.get("ONWIN_EXPERIMENT_PAGE") or DEFAULT_PAGE
    headless = os.environ.get("ONWIN_EXPERIMENT_HEADLESS", "0").strip() in ("1", "true", "True", "yes")
    timeout_s = int(os.environ.get("ONWIN_EXPERIMENT_TIMEOUT") or "180")

    report = {
        "started_at": _now(),
        "zenrows_used": False,
        "proxy_used": False,
        "production_code_imported": False,
        "page_url": page_url,
        "headless": headless,
        "timeout_s": timeout_s,
        "browser": {},
        "observed_request": {"observed": False},
        "test_a_browser_fetch": None,
        "test_b_required_state": None,
        "test_c_standalone_http": None,
        "persistent_session": None,
        "zenrows_comparison": {
            "ran": False,
            "reason": "Skipped: would invoke the frozen production OnWin/ZenRows path.",
        },
    }

    print()
    print("OnWin DIRECT API experiment (isolated, no ZenRows)")
    print(f"Started {_now()}")
    print(f"Page: {page_url}")
    print(f"Headless: {headless}  timeout={timeout_s}s")
    print()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        report["browser"] = {"page_loaded": False, "error": f"playwright_import: {type(exc).__name__}: {exc}"}
        report["classification"] = "INCONCLUSIVE"
        report["situation"] = situation_note("INCONCLUSIVE", report)
        report["failure"] = "playwright is not importable in this environment"
        return report

    box = {"req": None, "finished": False}
    browser = None
    context = None

    try:
        playwright_cm = sync_playwright()
        playwright = playwright_cm.start()
    except Exception as exc:
        report["browser"] = {"page_loaded": False, "error": f"playwright_start: {type(exc).__name__}: {exc}"}
        report["classification"] = "INCONCLUSIVE"
        report["situation"] = situation_note("INCONCLUSIVE", report)
        report["failure"] = "could not start Playwright"
        return report

    try:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as exc:
            report["browser"] = {
                "page_loaded": False,
                "error": f"chromium_launch: {type(exc).__name__}: {exc}",
            }
            report["failure"] = "could not launch local Chromium"
            report["classification"] = "INCONCLUSIVE"
            report["situation"] = situation_note("INCONCLUSIVE", report)
            return report

        context = browser.new_context(
            locale="tr-TR",
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()

        def on_request(request):
            if not _is_target_url(request.url):
                return
            if box["req"] is None:
                box["req"] = capture_from_request(request)

        def on_request_finished(request):
            if not _is_target_url(request.url):
                return
            if box["req"] is None:
                box["req"] = capture_from_request(request)
            box["finished"] = True
            box["response"] = request.response()

        page.on("request", on_request)
        page.on("requestfinished", on_request_finished)

        nav_error = None
        try:
            print("Navigating (listeners already attached)...")
            page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except Exception as exc:
            nav_error = f"{type(exc).__name__}: {exc}"
            print(f"Navigation error: {nav_error}")

        final_url = page.url
        title = ""
        try:
            title = page.title()
        except Exception:
            title = ""
        page_loaded = bool(final_url) and not final_url.startswith("chrome-error")
        report["browser"] = {
            "page_loaded": page_loaded,
            "final_url_host": urlsplit(final_url).hostname,
            "final_url_path": urlsplit(final_url).path,
            "title": title[:120],
            "navigation_error": nav_error,
            "cloudflare_interstitial": looks_like_interstitial(
                title, urlsplit(final_url).hostname
            ),
        }
        print(f"Browser page loaded: {'yes' if page_loaded else 'no'}")
        print(f"  host={report['browser']['final_url_host']} title={title[:80]!r}")
        if report["browser"]["cloudflare_interstitial"]:
            print("  Cloudflare interstitial suspected (page title).")

        print(f"Waiting up to {timeout_s}s for {TARGET} ...")
        deadline = time.time() + timeout_s
        while time.time() < deadline and not box["finished"]:
            page.wait_for_timeout(250)

        observed_ok = box["finished"] and box["req"] is not None
        print(f"get_main_line observed: {'yes' if observed_ok else 'no'}")

        if not observed_ok:
            report["observed_request"] = {
                "observed": False,
                "waited_s": timeout_s,
            }
            report["browser"]["get_main_line_observed"] = False
            if report["browser"].get("cloudflare_interstitial"):
                report["failure"] = (
                    "Cloudflare interstitial (Just a moment...); "
                    "get_main_line was never requested"
                )
            elif nav_error and not page_loaded:
                report["failure"] = "browser cannot load OnWin"
            else:
                report["failure"] = "OnWin loads but get_main_line is never requested"
            report["classification"] = classify(report)
            report["situation"] = situation_note(report["classification"], report)
            return report

        req = box["req"]
        response = box.get("response")
        observed = summarize_observed(req, response)
        report["observed_request"] = observed
        report["browser"]["get_main_line_observed"] = True

        print(f"  method={observed.get('method')} status={observed.get('response_status')}")
        print(f"  origin={observed.get('origin')} content-type={observed.get('content_type')}")
        print(f"  header names: {', '.join(observed.get('header_names') or [])}")
        print_secret_line("x-token", _header_lookup(req.get("headers") or {}, "x-token"))
        print_secret_line(
            "x-message-metadata",
            _header_lookup(req.get("headers") or {}, "x-message-metadata"),
        )
        print(f"  cookies on request: {'yes' if observed.get('cookies_on_request') else 'no'}")
        print(
            f"  response bytes={observed.get('response_bytes')} "
            f"json={observed.get('appears_json')} "
            f"keys={observed.get('top_level_keys')} "
            f"events={observed.get('event_count')}"
        )

        headers = req.get("headers") or {}
        url = req.get("url")
        method = req.get("method") or "POST"
        post_data = req.get("post_data")
        cookies = context.cookies()
        report["browser"]["cookie_count"] = len(cookies)

        print()
        print("TEST A — fetch() inside the established page context")
        raw_a = browser_fetch(page, url, method, headers, post_data, omit=None, credentials="include")
        test_a = slim_fetch_result(raw_a)
        report["test_a_browser_fetch"] = test_a
        print(
            f"  status={test_a.get('status')} bytes={test_a.get('response_bytes')} "
            f"json={test_a.get('appears_json')} events={test_a.get('event_count')} "
            f"error={test_a.get('error')}"
        )

        test_b = {"variants": []}
        if test_a.get("status") == 200:
            print()
            print("TEST B — which captured state is necessary (in-page fetch)")
            variants = [
                ("full", set(), "include"),
                ("omit_x-token", {"x-token"}, "include"),
                ("omit_x-message-metadata", {"x-message-metadata"}, "include"),
                ("omit_both_tokens", {"x-token", "x-message-metadata"}, "include"),
                ("credentials_omit", set(), "omit"),
            ]
            for name, omit, creds in variants:
                raw = browser_fetch(page, url, method, headers, post_data, omit=omit, credentials=creds)
                slim = slim_fetch_result(raw)
                slim["name"] = name
                slim["credentials"] = creds
                slim["omitted"] = sorted(omit)
                test_b["variants"].append(slim)
                print(f"  {name}: status={slim.get('status')} json={slim.get('appears_json')}")
            page.wait_for_timeout(8000)
            raw_p2 = browser_fetch(page, url, method, headers, post_data, omit=None, credentials="include")
            persist2 = slim_fetch_result(raw_p2)
            page.wait_for_timeout(3000)
            raw_p3 = browser_fetch(page, url, method, headers, post_data, omit=None, credentials="include")
            persist3 = slim_fetch_result(raw_p3)
            report["persistent_session"] = {
                "initial": {"status": test_a.get("status"), "success": test_a.get("status") == 200},
                "after_short_delay": {
                    "status": persist2.get("status"),
                    "success": persist2.get("status") == 200,
                    "latency_ms": persist2.get("latency_ms"),
                },
                "third_same_browser": {
                    "status": persist3.get("status"),
                    "success": persist3.get("status") == 200,
                    "latency_ms": persist3.get("latency_ms"),
                },
            }
            print()
            print("PERSISTENT SESSION")
            print(f"  second after delay: status={persist2.get('status')}")
            print(f"  third without restart: status={persist3.get('status')}")
        else:
            print("TEST B skipped (Test A did not return 200).")
            report["failure"] = report.get("failure") or (
                f"browser fetch status={test_a.get('status')} error={test_a.get('error')}"
            )
        report["test_b_required_state"] = test_b
        report["required_state"] = required_state_notes(test_b, observed)

        print()
        print("TEST C — standalone HTTP client (no proxy, no ZenRows)")
        test_c = standalone_http(url, method, headers, post_data, cookies)
        report["test_c_standalone_http"] = test_c
        print(
            f"  status={test_c.get('status')} bytes={test_c.get('response_bytes')} "
            f"json={test_c.get('appears_json')} challenge={test_c.get('looks_like_challenge')} "
            f"error={test_c.get('error')}"
        )

        report["classification"] = classify(report)
        report["situation"] = situation_note(report["classification"], report)
        report["finished_at"] = _now()
        return report
    except Exception as exc:
        report["failure"] = f"experiment exception: {type(exc).__name__}: {exc}"
        report.setdefault("browser", {})["error"] = report["failure"]
        report["classification"] = classify(report) if report.get("observed_request", {}).get("observed") else "INCONCLUSIVE"
        report["situation"] = situation_note(report["classification"], report)
        report["finished_at"] = _now()
        return report
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            playwright.stop()
        except Exception:
            pass


def write_report(report: dict) -> Path:
    _mkdir_out()
    path = OUT_DIR / "report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def print_final(report: dict) -> None:
    print()
    print("=" * 72)
    print("EXPERIMENT RESULT:", report.get("classification"))
    print("=" * 72)
    print(report.get("situation"))
    browser = report.get("browser") or {}
    observed = report.get("observed_request") or {}
    test_a = report.get("test_a_browser_fetch") or {}
    test_c = report.get("test_c_standalone_http") or {}
    persist = report.get("persistent_session") or {}
    print()
    print("Evidence")
    print(f"  browser page loaded: {'yes' if browser.get('page_loaded') else 'no'}")
    print(f"  get_main_line observed: {'yes' if observed.get('observed') else 'no'}")
    print(f"  browser request status: {observed.get('response_status')}")
    print(f"  direct browser-context replay status: {test_a.get('status')}")
    print(f"  standalone HTTP replay status: {test_c.get('status')}")
    print(f"  response size: {observed.get('response_bytes') or test_a.get('response_bytes')}")
    print(f"  event count: {observed.get('event_count') or test_a.get('event_count')}")
    second = (persist.get("after_short_delay") or {}).get("success")
    print(
        "  persistent-session second request: "
        + ("success" if second else "failure" if persist else "not_run")
    )
    print()
    print("Required state")
    print(json.dumps(report.get("required_state") or {}, indent=2))
    print()
    print("Production impact")
    print("  existing OnWin production feed unchanged")
    print("  live BetKanyon unchanged")
    print("  live Orbit unchanged")
    print("  prematch unchanged")
    print("  arbitrage engine unchanged")
    print("  frontend unchanged")
    print()
    print(f"Sanitized report: {OUT_DIR / 'report.json'}")


def main() -> int:
    report = run()
    write_report(report)
    print_final(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
