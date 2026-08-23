"""Fill Kolay90 login from environment. Never logs credential values."""

from __future__ import annotations

import os
import time

HOME = "https://kolay90.com/"


def credentials_configured() -> bool:
    user = (os.environ.get("KOLAY90_USERNAME") or "").strip()
    password = (os.environ.get("KOLAY90_PASSWORD") or "").strip()
    return bool(user and password)


def _looks_like_challenge(page) -> bool:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    return "just a moment" in title or "attention required" in title


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


def _fill_login(page, username: str, password: str) -> bool:
    scope = _login_scope(page)
    user_locators = [
        scope.locator('input[type="password"]').locator("xpath=preceding::input[1]"),
        scope.locator('input[name*="user" i]'),
        scope.locator('input[name*="email" i]'),
        scope.locator('input[id*="user" i]'),
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


def establish_session(page, timeout_s: int = 90) -> dict:
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
        page.wait_for_timeout(1000)

    if _looks_like_challenge(page):
        return {
            "ok": False,
            "reason": "Cloudflare interstitial still present after wait",
            "cloudflare": True,
            "logged_in": False,
        }

    page.wait_for_timeout(2000)
    if _login_scope(page).locator('input[type="password"]').count() == 0:
        for opener in (
            page.get_by_role("button", name="Giriş"),
            page.get_by_role("link", name="Giriş"),
            page.get_by_text("Giriş Yap", exact=False),
            page.get_by_text("Üye Girişi", exact=False),
        ):
            try:
                if opener.count() == 0:
                    continue
                opener.first.click(timeout=4000)
                page.wait_for_timeout(1500)
                if _login_scope(page).locator('input[type="password"]').count() > 0:
                    break
            except Exception:
                continue

    submitted = False
    if _login_scope(page).locator('input[type="password"]').count() > 0:
        submitted = _fill_login(page, username, password)
        if submitted:
            page.wait_for_timeout(4000)
    title = ""
    try:
        title = page.title()
    except Exception:
        title = ""
    return {
        "ok": True,
        "reason": None,
        "cloudflare": False,
        "login_form_submitted": submitted,
        "logged_in": submitted,
        "page_title": title[:120],
        "page_path": page.url,
    }
