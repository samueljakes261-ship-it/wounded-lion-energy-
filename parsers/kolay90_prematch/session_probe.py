"""Timed diagnostics for one persistent Kolay90 ZenRows page.

Does not click Cloudflare, solve CAPTCHA, or copy cookies.
Does not call getMaclar unless the real application is visible.
Never prints secrets.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / ".env.local", override=True)

from parsers.kolay90_prematch.browser import Kolay90PrematchBrowser
from parsers.kolay90_prematch.fetch import fetch_getmaclar
from parsers.kolay90_prematch.login import (
    HOME,
    _fill_login,
    _open_login,
    credentials_configured,
    inspect_page,
)
from parsers.kolay90_prematch.parser import count_oranlar, parse_payload, unwrap_events

SNAPSHOT_SECONDS = (0, 10, 30, 60, 120, 180)
TEXT_MARKERS = (
    "just a moment",
    "cloudflare",
    "privacy",
    "verify you are human",
    "checking your browser",
    "lütfen tekrar giriş yapınız",
    "lutfen tekrar giris",
    "giriş yap",
    "giris yap",
    "üye girişi",
    "uye girisi",
    "kolay90",
)
APP_COOKIE_HINTS = ("bet_cms", "cf_clearance")


def log(message: str) -> None:
    safe = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[KOLAY90 SESSION PROBE] {safe}", flush=True)


def safe_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    host = parts.netloc.split("@")[-1]
    return f"{parts.scheme}://{host}{parts.path}"


def cookie_names(context) -> list[str]:
    try:
        return [item.get("name") or "" for item in context.cookies() if item.get("name")]
    except Exception:
        return []


def capture_network(page) -> list[dict]:
    events: list[dict] = []

    def on_response(response) -> None:
        try:
            request = response.request
            events.append(
                {
                    "url": safe_url(response.url),
                    "status": response.status,
                    "resource": request.resource_type,
                }
            )
        except Exception:
            return

    page.on("response", on_response)
    return events


def page_environment(page) -> dict:
    try:
        return page.evaluate(
            """() => ({
                userAgent: navigator.userAgent,
                language: navigator.language,
                languages: navigator.languages,
                cookieEnabled: navigator.cookieEnabled,
                javaEnabled: typeof navigator.javaEnabled === 'function' ? navigator.javaEnabled() : null,
                jsEnabled: true,
                viewport: { w: window.innerWidth, h: window.innerHeight },
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                readyState: document.readyState,
                iframeCount: document.querySelectorAll('iframe').length,
                iframeSrcs: [...document.querySelectorAll('iframe')]
                    .map((el) => el.src || el.getAttribute('src') || '')
                    .slice(0, 8),
                scriptCount: document.querySelectorAll('script').length,
                storageKeys: {
                    local: Object.keys(localStorage || {}),
                    session: Object.keys(sessionStorage || {}),
                },
                text: ((document.body && document.body.innerText) || '').slice(0, 400),
            })"""
        )
    except Exception as exc:
        return {"error": type(exc).__name__}


def marker_flags(text: str) -> dict[str, bool]:
    blob = (text or "").lower()
    return {marker: marker in blob for marker in TEXT_MARKERS}


def storage_keys_only(env: dict) -> dict:
    storage = env.get("storageKeys") or {}
    return {
        "local": list(storage.get("local") or [])[:20],
        "session": list(storage.get("session") or [])[:20],
    }


def content_fingerprint(title: str, ready: str, text: str, url: str) -> str:
    raw = f"{safe_url(url)}|{title}|{ready}|{(text or '')[:200]}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def take_snapshot(page, network: list[dict], previous_fp: str | None = None) -> dict:
    env = page_environment(page)
    inspect = inspect_page(page)
    text = str(env.get("text") or "")
    names = cookie_names(page.context)
    fp = content_fingerprint(
        inspect.get("title") or env.get("readyState") or "",
        str(env.get("readyState") or ""),
        text,
        page.url,
    )
    recent = network[-8:]
    statuses = [item.get("status") for item in network if item.get("status") is not None]
    kolay_statuses = [
        item.get("status")
        for item in network
        if "kolay90.com" in (item.get("url") or "")
    ]
    iframe_srcs = [safe_url(src) for src in (env.get("iframeSrcs") or []) if src]
    return {
        "url": safe_url(page.url),
        "title": (inspect.get("title") or "")[:120],
        "readyState": env.get("readyState"),
        "login_form": bool(inspect.get("has_password")),
        "cloudflare": bool(inspect.get("cloudflare")),
        "application": bool(inspect.get("application")),
        "cf_clearance": "cf_clearance" in names,
        "bet_cms": "bet_cms" in names,
        "cookie_names": names,
        "cookie_count": len(names),
        "network_count": len(network),
        "recent_statuses": recent,
        "kolay90_statuses": kolay_statuses[-12:],
        "status_histogram": sorted({status: statuses.count(status) for status in statuses}.items()),
        "markers": marker_flags(f"{inspect.get('title')} {text}"),
        "iframe_count": env.get("iframeCount"),
        "iframe_urls": iframe_srcs,
        "script_count": env.get("scriptCount"),
        "storage_keys": storage_keys_only(env),
        "content_fp": fp,
        "content_changed": previous_fp is not None and fp != previous_fp,
        "userAgent": env.get("userAgent"),
        "language": env.get("language"),
        "viewport": env.get("viewport"),
        "timezone": env.get("timezone"),
        "cookieEnabled": env.get("cookieEnabled"),
        "jsEnabled": env.get("jsEnabled"),
        "button_labels": inspect.get("button_labels"),
        "input_types": inspect.get("input_types"),
    }


def log_snapshot(label: str, snap: dict) -> None:
    log(
        f"{label} url={snap['url']} title={snap['title']!r} "
        f"ready={snap['readyState']} cf={snap['cloudflare']} "
        f"login={snap['login_form']} app={snap['application']} "
        f"cf_clearance={snap['cf_clearance']} bet_cms={snap['bet_cms']} "
        f"cookies={snap['cookie_count']} names={snap['cookie_names']} "
        f"net={snap['network_count']} kolay_status={snap['kolay90_statuses']} "
        f"iframes={snap['iframe_count']} scripts={snap['script_count']} "
        f"changed={snap['content_changed']}"
    )
    log(f"{label} markers={ {k: v for k, v in snap['markers'].items() if v} }")
    log(f"{label} storage_keys={snap['storage_keys']} buttons={snap['button_labels']}")


def app_reached(snap: dict) -> bool:
    if snap.get("cloudflare"):
        return False
    if snap.get("login_form"):
        return True
    if snap.get("application") and not snap["markers"].get("just a moment"):
        return True
    return False


def try_login_and_getmaclar(page) -> dict:
    if not credentials_configured():
        return {"login": "SKIPPED", "reason": "credentials missing", "getmaclar": "NOT_REACHED"}
    inspect = inspect_page(page)
    if not inspect.get("has_password"):
        _open_login(page)
        inspect = inspect_page(page)
    if not inspect.get("has_password"):
        return {"login": "FAILED", "reason": "login form not found", "getmaclar": "NOT_REACHED"}
    username = (os.environ.get("KOLAY90_USERNAME") or "").strip()
    password = (os.environ.get("KOLAY90_PASSWORD") or "").strip()
    submitted = _fill_login(page, username, password)
    if not submitted:
        return {"login": "FAILED", "reason": "submit failed", "getmaclar": "NOT_REACHED"}
    page.wait_for_timeout(5000)
    after = inspect_page(page)
    logged_in = after.get("has_account") or (submitted and not after.get("has_password"))
    if not logged_in:
        return {
            "login": "FAILED",
            "reason": "no authenticated application state",
            "getmaclar": "NOT_REACHED",
        }
    raw = fetch_getmaclar(page)
    events = unwrap_events(raw.get("payload"))
    matches = parse_payload(raw.get("payload"))
    counts = count_oranlar(events)
    example = None
    if matches:
        row = matches[0]
        example = {
            "home": row.home_team,
            "away": row.away_team,
            "HOME": row.raw_home,
            "DRAW": row.raw_draw,
            "AWAY": row.raw_away,
        }
    authenticated = bool(events) and not raw.get("unauthenticated")
    return {
        "login": "SUCCESS" if logged_in else "FAILED",
        "getmaclar": "SUCCESS" if authenticated else (
            "UNAUTHENTICATED" if raw.get("unauthenticated") else "NOT_REACHED"
        ),
        "status": raw.get("status"),
        "content_type": raw.get("content_type"),
        "bytes": raw.get("bytes"),
        "total_events": len(events),
        "with_any_1x2": counts["with_any_1x2"],
        "with_all_1x2": counts["with_all_1x2"],
        "incomplete_1x2": max(0, counts["with_any_1x2"] - counts["with_all_1x2"]),
        "example": example,
    }


def main() -> int:
    if not (os.environ.get("ZENROWS_BROWSER_WS") or "").strip():
        log("ZENROWS_BROWSER_WS is not set")
        return 2
    browser = Kolay90PrematchBrowser()
    page = browser.page()
    network = capture_network(page)
    log("browser_established=YES persistent=YES source=ZENROWS_BROWSER_WS")
    started = time.monotonic()
    page.goto(HOME, wait_until="domcontentloaded", timeout=120000)
    snapshots = []
    previous_fp = None
    for mark in SNAPSHOT_SECONDS:
        remaining = mark - (time.monotonic() - started)
        if remaining > 0:
            page.wait_for_timeout(int(remaining * 1000))
        snap = take_snapshot(page, network, previous_fp)
        previous_fp = snap["content_fp"]
        snapshots.append(snap)
        log_snapshot(f"t={mark}s", snap)
        if mark == 0:
            log(
                f"env ua={snap.get('userAgent')} lang={snap.get('language')} "
                f"tz={snap.get('timezone')} viewport={snap.get('viewport')} "
                f"cookies_enabled={snap.get('cookieEnabled')} js={snap.get('jsEnabled')}"
            )

    last = snapshots[-1]
    reached = any(app_reached(item) for item in snapshots) or (
        last.get("cf_clearance") and not last.get("cloudflare")
    )
    if not reached:
        log("KOLAY90_CLOUDFLARE_BLOCKED")
        log(
            f"boundary=cloudflare_challenge cf_clearance={last['cf_clearance']} "
            f"bet_cms={last['bet_cms']} app_requests={last['kolay90_statuses']}"
        )
        browser.close()
        return 4

    if not last.get("login_form"):
        log("Cloudflare cleared; navigating home on the same page to look for login")
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        last = take_snapshot(page, network, last.get("content_fp"))
        log_snapshot("post-home", last)
        if last.get("cloudflare"):
            log("KOLAY90_CLOUDFLARE_BLOCKED")
            browser.close()
            return 4

    log("Kolay90 application reached; attempting login on the same page")
    result = try_login_and_getmaclar(page)
    log(f"login={result.get('login')} getmaclar={result.get('getmaclar')}")
    if result.get("example"):
        log(f"example={result['example']}")
    if result.get("total_events") is not None:
        log(
            f"events={result.get('total_events')} any={result.get('with_any_1x2')} "
            f"all={result.get('with_all_1x2')} incomplete={result.get('incomplete_1x2')}"
        )
    browser.close()
    return 0 if result.get("getmaclar") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
