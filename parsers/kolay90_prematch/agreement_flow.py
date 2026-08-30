"""Complete Kolay90 flow: CF wait -> agreement accept -> login -> getMaclar.

One persistent ZenRows page. No Cloudflare interaction. No cookie replay.
Never prints secrets.
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
load_dotenv(ROOT / ".env.local", override=True)

from parsers.kolay90_prematch.agreement import (
    accept_agreement_page,
    collect_visible_buttons,
    is_agreement_page,
)
from parsers.kolay90_prematch.browser import Kolay90PrematchBrowser
from parsers.kolay90_prematch.fetch import fetch_getmaclar
from parsers.kolay90_prematch.login import (
    HOME,
    _fill_login,
    _looks_like_challenge,
    _open_login,
    credentials_configured,
    inspect_page,
)
from parsers.kolay90_prematch.parser import count_oranlar, parse_payload, unwrap_events
from parsers.kolay90_prematch.session_probe import log, safe_url


CF_WAIT_S = 180
POST_ACCEPT_WAIT_S = 20


def failure(code: str, **extra) -> dict:
    row = {"boundary": code, **extra}
    return row


def visible_buttons(page) -> list[dict]:
    return collect_visible_buttons(page)


def page_text(page) -> str:
    try:
        return page.evaluate(
            "() => ((document.body && document.body.innerText) || '').slice(0, 1200)"
        ) or ""
    except Exception:
        return ""


def current_state(page) -> dict:
    inspect = inspect_page(page)
    url = page.url or ""
    title = inspect.get("title") or ""
    text = page_text(page)
    return {
        "url": safe_url(url),
        "title": title[:120],
        "cloudflare": _looks_like_challenge(page),
        "agreement": is_agreement_page(url, title, text),
        "login_form": bool(inspect.get("has_password")),
        "application": bool(inspect.get("application")),
        "has_account": bool(inspect.get("has_account")),
        "buttons": [item.get("text") for item in visible_buttons(page)][:12],
    }


def wait_for_progress(page, timeout_s: int = CF_WAIT_S) -> dict:
    deadline = time.time() + timeout_s
    last = current_state(page)
    log(f"observe url={last['url']} title={last['title']!r} cf={last['cloudflare']} agreement={last['agreement']}")
    cleared_at = None
    while time.time() < deadline:
        last = current_state(page)
        if last["agreement"] or last["login_form"]:
            return last
        if not last["cloudflare"]:
            if cleared_at is None:
                cleared_at = time.time()
            elif time.time() - cleared_at >= 12:
                return last
        page.wait_for_timeout(2000)
    return last


def accept_agreement(page) -> dict:
    result = accept_agreement_page(page)
    log(
        f"AGREEMENT_ACCEPT_BUTTON_FOUND={'YES' if result.get('found') else 'NO'} "
        f"accept={result.get('accept_candidates')} reject={result.get('reject_candidates')}"
    )
    if not result.get("found"):
        return {
            **result,
            "url": safe_url(page.url),
            "title": (page.title() or "")[:120],
        }
    page.wait_for_timeout(2500)
    after = current_state(page)
    return {
        **result,
        "url": after["url"],
        "title": after["title"],
        "now_login": after["login_form"],
        "now_cf": after["cloudflare"],
    }


def do_login(page) -> dict:
    if not credentials_configured():
        return {"ok": False, "reason": "credentials_missing"}
    state = current_state(page)
    if not state["login_form"]:
        _open_login(page)
        page.wait_for_timeout(1500)
        state = current_state(page)
    if not state["login_form"]:
        return {"ok": False, "reason": "login_form_not_found", "url": state["url"], "title": state["title"]}
    username = (os.environ.get("KOLAY90_USERNAME") or "").strip()
    password = (os.environ.get("KOLAY90_PASSWORD") or "").strip()
    submitted = _fill_login(page, username, password)
    if not submitted:
        return {"ok": False, "reason": "submit_failed", "url": safe_url(page.url)}
    page.wait_for_timeout(5000)
    after = current_state(page)
    authenticated = after.get("has_account") or (submitted and not after.get("login_form") and not after.get("cloudflare"))
    return {
        "ok": authenticated,
        "submitted": submitted,
        "url": after["url"],
        "title": after["title"],
        "login_form_remaining": after["login_form"],
        "has_account": after["has_account"],
    }


def summarize_fetch(raw: dict) -> dict:
    payload = raw.get("payload")
    events = unwrap_events(payload)
    matches = parse_payload(payload)
    counts = count_oranlar(events)
    hata = payload.get("hata") if isinstance(payload, dict) else None
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
    if raw.get("unauthenticated"):
        kind = "UNAUTHENTICATED_JSON"
    elif raw.get("cloudflare") or raw.get("status") == 403:
        kind = "403"
    elif events and not raw.get("unauthenticated"):
        kind = "AUTHENTICATED_JSON"
    else:
        kind = "NOT_REACHED"
    return {
        "kind": kind,
        "status": raw.get("status"),
        "content_type": raw.get("content_type"),
        "hata": hata,
        "total_events": len(events),
        "with_any_1x2": counts["with_any_1x2"],
        "with_all_1x2": counts["with_all_1x2"],
        "example": example,
    }


def poll_getmaclar(page) -> list[dict]:
    rows = []
    first = summarize_fetch(fetch_getmaclar(page))
    rows.append(first)
    log(f"getMaclar#1 status={first['status']} kind={first['kind']} events={first['total_events']} 1x2={first['with_all_1x2']}")
    if first["kind"] != "AUTHENTICATED_JSON":
        return rows
    page.wait_for_timeout(30_000)
    second = summarize_fetch(fetch_getmaclar(page))
    rows.append(second)
    log(f"getMaclar#2 status={second['status']} kind={second['kind']} events={second['total_events']} 1x2={second['with_all_1x2']}")
    page.wait_for_timeout(60_000)
    third = summarize_fetch(fetch_getmaclar(page))
    rows.append(third)
    log(f"getMaclar#3 status={third['status']} kind={third['kind']} events={third['total_events']} 1x2={third['with_all_1x2']}")
    return rows


def main() -> int:
    if not (os.environ.get("ZENROWS_BROWSER_WS") or "").strip():
        log("ZENROWS_BROWSER_WS is not set")
        return 2
    browser = Kolay90PrematchBrowser()
    try:
        page = browser.page()
    except Exception:
        log("ZENROWS_BROWSER=FAILED persistent=NO source=ZENROWS_BROWSER_WS")
        log("boundary=A ZenRows browser failed to establish")
        try:
            browser.close()
        except Exception:
            pass
        return 3
    log("ZENROWS_BROWSER=SUCCESS persistent=YES source=ZENROWS_BROWSER_WS")
    try:
        page.goto(HOME, wait_until="domcontentloaded", timeout=120000)
        state = wait_for_progress(page, CF_WAIT_S)
        log(f"after_wait url={state['url']} title={state['title']!r} cf={state['cloudflare']} agreement={state['agreement']} login={state['login_form']}")

        if state["cloudflare"] and not state["agreement"] and not state["login_form"]:
            log("boundary=B Cloudflare never progressed")
            log("CLOUDFLARE=BLOCKED AGREEMENT_PAGE=NOT_REACHED")
            return 4

        log("CLOUDFLARE=PASSED")
        agreement = {"reached": False, "found": False, "clicked": False}
        if state["agreement"]:
            agreement = accept_agreement(page)
            log(
                f"AGREEMENT_PAGE_REACHED=YES AGREEMENT_ACCEPT_BUTTON_FOUND="
                f"{'YES' if agreement['found'] else 'NO'} "
                f"AGREEMENT_ACCEPTED={'YES' if agreement['clicked'] else 'NO'} "
                f"POST_AGREEMENT_URL={agreement.get('url')}"
            )
            if not agreement["clicked"]:
                log("boundary=D Agreement appeared but accept action failed")
                return 5
            page.wait_for_timeout(POST_ACCEPT_WAIT_S * 1000)
            state = current_state(page)
            log(f"post_accept url={state['url']} title={state['title']!r} login={state['login_form']} cf={state['cloudflare']}")
        else:
            log("AGREEMENT_PAGE=NOT_REACHED")

        if state["cloudflare"]:
            log("boundary=B returned to Cloudflare after agreement")
            return 4
        if not state["login_form"]:
            _open_login(page)
            page.wait_for_timeout(2000)
            state = current_state(page)
        if not state["login_form"]:
            log("boundary=E Login page never appeared")
            log(f"LOGIN_PAGE=NOT_REACHED url={state['url']} title={state['title']!r} buttons={state['buttons']}")
            return 6

        log("LOGIN_PAGE=REACHED")
        login = do_login(page)
        log(f"LOGIN submitted={login.get('submitted')} ok={login.get('ok')} url={login.get('url')} title={login.get('title')!r}")
        if not login.get("ok"):
            log(f"boundary=F Login failed reason={login.get('reason')}")
            return 7

        log("AUTHENTICATION=SUCCESS")
        polls = poll_getmaclar(page)
        first = polls[0]
        log(f"GETMACLAR={first['kind']} EVENT_COUNT={first['total_events']} 1X2_EVENT_COUNT={first['with_all_1x2']}")
        if first.get("example"):
            log(f"example={first['example']}")
        if first["kind"] == "UNAUTHENTICATED_JSON":
            log("boundary=G Authentication succeeded but getMaclar returned unauthenticated")
            return 8
        if first["kind"] == "403":
            log("boundary=H getMaclar returned Cloudflare/403")
            return 9
        if first["kind"] != "AUTHENTICATED_JSON":
            log("boundary=G getMaclar did not return match JSON")
            return 8
        if len(polls) < 3 or any(row["kind"] != "AUTHENTICATED_JSON" for row in polls):
            log("boundary=J First request worked but subsequent requests failed")
            log("PERSISTENT_BROWSER_FETCH=FAILED ZENROWS_PER_POLL_REQUIRED=UNKNOWN")
            return 10
        log("boundary=I getMaclar returned authenticated JSON")
        log("PERSISTENT_BROWSER_FETCH=SUCCESS ZENROWS_PER_POLL_REQUIRED=NO")
        return 0
    finally:
        # Keep process diagnostics complete; close only this isolated browser.
        try:
            browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
