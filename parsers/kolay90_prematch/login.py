"""Fill Kolay90 login from environment. Never logs credential values."""

from __future__ import annotations

import os
import time

from parsers.kolay90_prematch.agreement import (
    accept_agreement_page,
    is_agreement_page,
)

HOME = "https://kolay90.com/"
APP_MARKERS = (
    "giriş",
    "giris",
    "kolay90",
    "canlı",
    "canli",
    "maçlar",
    "maclar",
    "bahis",
    "spor",
)


def credentials_configured() -> bool:
    user = (os.environ.get("KOLAY90_USERNAME") or "").strip()
    password = (os.environ.get("KOLAY90_PASSWORD") or "").strip()
    return bool(user and password)


def _looks_like_challenge(page) -> bool:
    try:
        title = (page.title() or "").lower()
        url = (page.url or "").lower()
    except Exception:
        return True
    if any(
        token in title
        for token in (
            "just a moment",
            "un momento",
            "un moment",
            "einen moment",
            "bitte warten",
            "attention required",
            "checking your browser",
            "verify you are human",
        )
    ):
        return True
    if "__cf_chl" in url or "challenge-platform" in url:
        return True
    return False


def inspect_page(page) -> dict:
    try:
        snapshot = page.evaluate(
            """() => {
                const visible = (el) => !!(el && (el.offsetWidth || el.offsetHeight));
                const inputs = [...document.querySelectorAll('input')]
                    .filter(visible)
                    .map((el) => ({
                        type: el.type || '',
                        name: el.name || '',
                        id: el.id || '',
                        placeholder: (el.placeholder || '').slice(0, 40),
                    }));
                const buttons = [...document.querySelectorAll(
                    'button, input[type=submit], [role=button], a'
                )]
                    .filter(visible)
                    .map((el) => (el.innerText || el.value || el.getAttribute('aria-label') || '')
                        .trim().slice(0, 40))
                    .filter(Boolean)
                    .slice(0, 25);
                const text = ((document.body && document.body.innerText) || '')
                    .toLowerCase().slice(0, 500);
                return {
                    title: document.title || '',
                    href: location.pathname + location.search,
                    inputs,
                    buttons,
                    text,
                };
            }"""
        )
    except Exception:
        snapshot = {
            "title": "",
            "href": "",
            "inputs": [],
            "buttons": [],
            "text": "",
        }
    title = str(snapshot.get("title") or "")
    href = str(snapshot.get("href") or "")
    text = str(snapshot.get("text") or "")
    inputs = snapshot.get("inputs") or []
    buttons = snapshot.get("buttons") or []
    blob = f"{title} {href} {text}".lower()
    challenge = _looks_like_challenge(page) or any(
        token in blob
        for token in ("just a moment", "un momento", "un moment", "einen moment")
    )
    has_password = any(item.get("type") == "password" for item in inputs)
    has_login_control = has_password or any(
        "giriş" in str(btn).lower() or "giris" in str(btn).lower() or "login" in str(btn).lower()
        for btn in buttons
    )
    has_app_marker = any(marker in blob for marker in APP_MARKERS)
    has_account = any(
        token in blob
        for token in ("çıkış", "cikis", "logout", "hesabım", "hesabim", "bakiye")
    )
    return {
        "title": title[:120],
        "path": href[:160],
        "cloudflare": challenge,
        "application": (not challenge) and (has_app_marker or has_login_control),
        "has_password": has_password,
        "has_login_control": has_login_control,
        "has_account": has_account,
        "input_types": [item.get("type") for item in inputs][:12],
        "input_names": [item.get("name") for item in inputs if item.get("name")][:8],
        "button_labels": buttons[:12],
    }


def _login_scope(page):
    try:
        if page.locator('input[type="password"]').count() > 0:
            return page
    except Exception:
        pass
    for frame in page.frames:
        try:
            if frame.locator('input[type="password"]').count() > 0:
                return frame
        except Exception:
            continue
    return page


def _open_login(page) -> None:
    for opener in (
        page.get_by_role("button", name="Giriş"),
        page.get_by_role("link", name="Giriş"),
        page.get_by_text("Giriş Yap", exact=False),
        page.get_by_text("Üye Girişi", exact=False),
        page.get_by_text("Giriş", exact=True),
    ):
        try:
            if opener.count() == 0:
                continue
            opener.first.click(timeout=4000)
            page.wait_for_timeout(1500)
            if _login_scope(page).locator('input[type="password"]').count() > 0:
                return
        except Exception:
            continue


def _fill_login(page, username: str, password: str) -> bool:
    scope = _login_scope(page)
    user_locators = [
        scope.locator('input[type="password"]').locator("xpath=preceding::input[1]"),
        scope.locator('input[name*="user" i]'),
        scope.locator('input[name*="email" i]'),
        scope.locator('input[id*="user" i]'),
        scope.locator('input[autocomplete="username"]'),
        scope.locator('input[type="text"]'),
        scope.locator('input[type="email"]'),
        scope.get_by_placeholder("Kullanıcı", exact=False),
        scope.get_by_placeholder("Username", exact=False),
    ]
    password_box = scope.locator('input[type="password"]').first
    if password_box.count() == 0:
        return False
    filled_user = False
    for locator in user_locators:
        try:
            if locator.count() == 0:
                continue
            target = locator.first
            if not target.is_visible():
                continue
            target.fill(username, timeout=5000)
            filled_user = True
            break
        except Exception:
            continue
    if not filled_user:
        return False
    password_box.fill(password, timeout=5000)
    submitted = False
    for clickable in (
        scope.get_by_role("button", name="Giriş"),
        scope.get_by_role("button", name="Login"),
        scope.locator('button[type="submit"]'),
        scope.locator('input[type="submit"]'),
        scope.get_by_text("Giriş Yap", exact=False),
        page.get_by_role("button", name="Giriş"),
        page.get_by_text("Giriş Yap", exact=False),
    ):
        try:
            if clickable.count() == 0:
                continue
            clickable.first.click(timeout=5000)
            submitted = True
            break
        except Exception:
            continue
    if not submitted:
        try:
            password_box.press("Enter")
            submitted = True
        except Exception:
            return False
    return submitted


def establish_session(page, timeout_s: int = 180) -> dict:
    username = (os.environ.get("KOLAY90_USERNAME") or "").strip()
    password = (os.environ.get("KOLAY90_PASSWORD") or "").strip()
    if not username or not password:
        return {
            "ok": False,
            "reason": "KOLAY90_USERNAME / KOLAY90_PASSWORD are not set",
            "cloudflare": False,
            "logged_in": False,
        }

    page.goto(HOME, wait_until="domcontentloaded", timeout=timeout_s * 1000)
    deadline = time.time() + timeout_s
    while time.time() < deadline and _looks_like_challenge(page):
        page.wait_for_timeout(2000)

    settle = min(deadline, time.time() + 12)
    snapshot = inspect_page(page)
    while time.time() < settle:
        snapshot = inspect_page(page)
        if is_agreement_page(
            page.url or "", snapshot.get("title") or "", snapshot.get("text") or ""
        ) or snapshot.get("has_password"):
            break
        page.wait_for_timeout(1500)

    snapshot = inspect_page(page)
    agreement_url = page.url or ""
    if is_agreement_page(agreement_url, snapshot.get("title") or "", snapshot.get("text") or ""):
        accepted = accept_agreement_page(page)
        snapshot["agreement"] = accepted
        if not accepted.get("clicked"):
            return {
                "ok": False,
                "reason": "agreement_accept_failed",
                "cloudflare": False,
                "logged_in": False,
                "login_form_found": False,
                "login_form_submitted": False,
                "page_title": snapshot["title"],
                "page_path": snapshot["path"],
                "inspect": snapshot,
            }
        page.wait_for_timeout(5000)
        snapshot = inspect_page(page)
        snapshot["agreement"] = accepted

    if snapshot["cloudflare"] or not snapshot["application"]:
        return {
            "ok": False,
            "reason": "KOLAY90_CLOUDFLARE_SESSION_FAILED",
            "cloudflare": True,
            "logged_in": False,
            "login_form_found": False,
            "login_form_submitted": False,
            "page_title": snapshot["title"],
            "page_path": snapshot["path"],
            "inspect": snapshot,
        }

    if not snapshot["has_password"]:
        _open_login(page)
        snapshot = inspect_page(page)

    submitted = False
    form_found = snapshot["has_password"]
    if form_found:
        submitted = _fill_login(page, username, password)
        if submitted:
            page.wait_for_timeout(5000)
            snapshot = inspect_page(page)

    return {
        "ok": True,
        "reason": None,
        "cloudflare": False,
        "login_form_found": form_found,
        "login_form_submitted": submitted,
        "logged_in": submitted and not snapshot["has_password"],
        "page_title": snapshot["title"],
        "page_path": snapshot["path"],
        "inspect": snapshot,
    }
