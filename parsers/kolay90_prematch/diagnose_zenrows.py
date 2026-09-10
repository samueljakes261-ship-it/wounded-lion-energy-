"""Isolated ZenRows connect diagnosis for Kolay90.

Does not call CredentialManager.report_failure / report_success, so
BetKanyon/OnWin runtime state is not written. Does not fetch getMaclar.
Never prints secrets.
"""

from __future__ import annotations

import os
import re
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

from credentials.failures import classify_zenrows_error
from credentials.manager import get_manager
from credentials.store import CredentialStore
from credentials.zenrows_provider import apply_persistent_session_ttl


def log(message: str) -> None:
    print(f"[KOLAY90 ZENROWS DIAG] {message}")


def env_key_names(path: Path) -> list[str]:
    if not path.exists():
        return []
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        names.append(stripped.split("=", 1)[0])
    return names


def mask_tail(value: str) -> str:
    if not value:
        return "(empty)"
    tail = value[-4:] if len(value) >= 4 else value
    return f"********{tail}"


def apikey_fingerprint(browser_ws: str) -> str:
    if not browser_ws:
        return "(empty)"
    pairs = parse_qsl(urlsplit(browser_ws).query, keep_blank_values=True)
    for key, value in pairs:
        if key.lower() in ("apikey", "api_key"):
            return mask_tail(value)
    return mask_tail(browser_ws)


def ws_shape(browser_ws: str) -> dict:
    if not browser_ws:
        return {"present": False}
    parts = urlsplit(browser_ws)
    query_keys = [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    return {
        "present": True,
        "scheme": parts.scheme,
        "host": parts.netloc.split("@")[-1],
        "path": parts.path or "/",
        "query_keys": query_keys,
        "apikey_fingerprint": apikey_fingerprint(browser_ws),
    }


def redact_error(text: str) -> str:
    redacted = text
    redacted = re.sub(r"(?i)apikey=[^&\s'\"]+", "apikey=***", redacted)
    redacted = re.sub(r"(?i)(authorization:\s*)\S+", r"\1***", redacted)
    redacted = re.sub(r"wss://[^\s'\"]+", "wss://***", redacted)
    redacted = re.sub(r"ws://[^\s'\"]+", "ws://***", redacted)
    redacted = re.sub(r"https://browser\.zenrows\.com[^\s'\"]*", "https://browser.zenrows.com/***", redacted)
    redacted = re.sub(r"(?i)(__cf_chl[^=]*=)[^&\s'\"]+", r"\1***", redacted)
    return redacted[:800]


def looks_like_challenge(title: str, url: str) -> bool:
    blob = f"{title} {url}".lower()
    return "just a moment" in blob or "attention required" in blob or "cloudflare" in blob


def inventory() -> dict:
    store = CredentialStore()
    stored = store.load_credentials_if_exists()
    state = store.load_state()
    manager = get_manager("zenrows")
    loaded, loaded_state = manager._load()

    stored_view = []
    for cred in stored:
        stored_view.append(
            {
                "credential_id": cred.credential_id,
                "provider": cred.provider,
                "enabled": cred.enabled,
                "label": cred.label,
                "created_at": cred.created_at,
                "secret_kind": "env_ref" if cred.encrypted_secret.startswith("env:") else "encrypted",
                "env_ref": cred.encrypted_secret[4:] if cred.encrypted_secret.startswith("env:") else None,
            }
        )

    state_view = {
        credential_id: runtime.to_dict()
        for credential_id, runtime in state.items()
    }
    selected = manager.select()
    return {
        "store_path": store.store_path,
        "state_path": store.state_path,
        "store_exists": Path(store.store_path).exists(),
        "state_exists": Path(store.state_path).exists(),
        "stored_credentials": stored_view,
        "runtime_state": state_view,
        "manager_loaded_ids": [c.credential_id for c in loaded],
        "manager_selected_id": selected.credential_id if selected else None,
        "retry_after": manager.seconds_until_available(),
        "env_files": {
            ".env": env_key_names(ROOT / ".env"),
            ".env.local": env_key_names(ROOT / ".env.local"),
        },
        "ZENROWS_BROWSER_WS_set": bool((os.getenv("ZENROWS_BROWSER_WS") or "").strip()),
        "legacy_ws_shape": ws_shape((os.getenv("ZENROWS_BROWSER_WS") or "").strip()),
        "loaded_source": (
            "credentials.json"
            if any(c.credential_id != "zenrows-env-legacy" for c in loaded)
            else "ZENROWS_BROWSER_WS legacy fallback"
        ),
    }


def connect_without_health_write(browser_ws: str) -> dict:
    from playwright.sync_api import sync_playwright

    connect_url = apply_persistent_session_ttl(browser_ws)
    started = time.monotonic()
    result = {
        "connected": False,
        "exception_type": None,
        "redacted_error": None,
        "classified_as": None,
        "page_loaded": False,
        "page_url": None,
        "page_title": None,
        "http_status": None,
        "cloudflare": False,
        "connect_ms": None,
        "navigate_ms": None,
    }
    playwright = None
    browser = None
    page = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.connect_over_cdp(connect_url)
        result["connected"] = True
        result["connect_ms"] = int((time.monotonic() - started) * 1000)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        nav_started = time.monotonic()
        response = page.goto("https://kolay90.com", wait_until="domcontentloaded", timeout=90000)
        result["navigate_ms"] = int((time.monotonic() - nav_started) * 1000)
        result["page_loaded"] = True
        result["page_url"] = page.url
        result["page_title"] = (page.title() or "")[:120]
        result["http_status"] = response.status if response else None
        result["cloudflare"] = looks_like_challenge(result["page_title"], result["page_url"] or "")
    except Exception as exc:
        result["connect_ms"] = int((time.monotonic() - started) * 1000)
        result["exception_type"] = type(exc).__name__
        result["redacted_error"] = redact_error(str(exc))
        result["classified_as"] = classify_zenrows_error(exc).value
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
    return result


def main() -> int:
    info = inventory()
    log(f"store_path={info['store_path']} exists={info['store_exists']}")
    log(f"state_path={info['state_path']} exists={info['state_exists']}")
    log(f"env .env keys={info['env_files']['.env']}")
    log(f"env .env.local keys={info['env_files']['.env.local']}")
    log(f"ZENROWS_BROWSER_WS set={info['ZENROWS_BROWSER_WS_set']}")
    log(f"legacy_ws_shape={info['legacy_ws_shape']}")
    log(f"stored_credentials={info['stored_credentials']}")
    log(f"runtime_state={info['runtime_state']}")
    log(f"manager_loaded_ids={info['manager_loaded_ids']}")
    log(f"manager_selected_id={info['manager_selected_id']}")
    log(f"manager_source={info['loaded_source']}")
    log(f"retry_after={info['retry_after']}")

    browser_ws = (os.getenv("ZENROWS_BROWSER_WS") or "").strip()
    if not browser_ws:
        log("STOP: ZENROWS_BROWSER_WS is empty; no secret to test")
        return 2

    log("Connecting via Playwright CDP using ZENROWS_BROWSER_WS (no credential-state write)")
    probe = connect_without_health_write(browser_ws)
    for key in (
        "connected",
        "connect_ms",
        "exception_type",
        "classified_as",
        "redacted_error",
        "page_loaded",
        "http_status",
        "page_title",
        "page_url",
        "cloudflare",
        "navigate_ms",
    ):
        log(f"{key}={probe.get(key)}")
    log("getMaclar=NOT RUN")
    return 0 if probe.get("connected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
