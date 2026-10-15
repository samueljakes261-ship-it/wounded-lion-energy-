"""Isolated BetKanyon prematch acquisition experiment.

Does NOT start workers, modify parsers, or use ZenRows.

Order:
  1. Plain Python HTTP (requests)
  2. Local persistent Chromium (Playwright), only if HTTP fails
  3. Session-requirement notes, only if both fail

Raw encrypted/decrypted bodies are written under %TEMP% only,
never into the repo or experiments/decrypt/.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers.betkanyon_prematch.decrypt import PrematchDecryptor
from parsers.betkanyon_prematch.fetcher import PREMATCH_PAGE, build_prematch_url
from parsers.betkanyon_prematch.parser import parse_prematch

TOURNAMENT_ID = "4520"
OUT_DIR = Path(tempfile.gettempdir()) / "arbscanner-bk-prematch-direct"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://betkanyon1617.com",
    "Referer": PREMATCH_PAGE,
}


def _out_path(name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / name


def _payload_kind(value) -> str:
    if value is None:
        return "missing"
    if isinstance(value, (dict, list)):
        return f"json_{type(value).__name__}"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "empty_string"
        if text[:1] in "{[":
            return f"json_text(len={len(text)})"
        return f"encrypted_string(len={len(text)})"
    return type(value).__name__


def _extract_payload(body):
    if isinstance(body, dict):
        return body.get("payload") or body.get("Payload") or body
    return body


def _summarize_response(status: int, content_type: str, text: str, body) -> dict:
    return {
        "status": status,
        "content_type": content_type,
        "body_bytes": len(text.encode("utf-8", "replace")),
        "looks_like_html": "<html" in text[:400].lower() or text.lstrip()[:15].lower().startswith("<!doctype"),
        "payload_kind": _payload_kind(_extract_payload(body) if not isinstance(body, str) else body),
        "text_prefix": text[:180].replace("\n", " "),
    }


def _inspect_1x2(decrypted) -> dict:
    events, stats = parse_prematch(decrypted)
    sample = []
    for event in events[:8]:
        sample.append(
            {
                "home": event.get("home"),
                "away": event.get("away"),
                "home_odds": event.get("home_odds"),
                "draw_odds": event.get("draw_odds"),
                "away_odds": event.get("away_odds"),
                "competition": event.get("competition"),
            }
        )
    return {"stats": stats, "sample": sample, "event_count": len(events)}


def _try_decrypt(payload) -> dict:
    if not isinstance(payload, str) or len(payload.strip()) < 20:
        return {"ok": False, "reason": f"payload is {_payload_kind(payload)}, not encrypted text"}
    try:
        decrypted = PrematchDecryptor().decrypt(payload)
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    inspection = _inspect_1x2(decrypted)
    structure = {}
    if isinstance(decrypted, dict):
        structure = {
            "keys": list(decrypted.keys())[:24],
            "SId": decrypted.get("SId"),
            "SN": decrypted.get("SN"),
            "TId": decrypted.get("TId"),
            "TN": decrypted.get("TN"),
            "events": len(decrypted.get("events") or []),
        }
    return {"ok": True, "structure": structure, **inspection}


def approach_http(url: str) -> dict:
    print("==================================================")
    print("APPROACH 1 — plain Python HTTP (no ZenRows, no browser)")
    print("==================================================")
    print(f"GET {urlparse(url).path}?tournamentId={TOURNAMENT_ID}&includeLiveEvents=false")
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"FAILED: {result['error']}")
        return result
    text = response.text
    content_type = response.headers.get("Content-Type", "")
    body = None
    try:
        body = response.json()
    except Exception:
        body = None
    summary = _summarize_response(response.status_code, content_type, text, body)
    print(f"HTTP {summary['status']} content_type={content_type!r}")
    print(f"payload_kind={summary['payload_kind']} html={summary['looks_like_html']}")
    _out_path("http_meta.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    payload = _extract_payload(body) if body is not None else text
    if summary["looks_like_html"] or response.status_code >= 400:
        print("Direct HTTP did not return a JSON betting payload.")
        return {"ok": False, "summary": summary}
    if isinstance(payload, str) and len(payload) > 20:
        _out_path("http_encrypted.txt").write_text(payload, encoding="utf-8")
    decrypt = _try_decrypt(payload if isinstance(payload, str) else json.dumps(payload))
    if decrypt.get("ok"):
        print(
            f"DECRYPT OK events={decrypt['structure'].get('events')} "
            f"valid_1x2={decrypt['event_count']}"
        )
        for row in decrypt["sample"][:5]:
            print(
                f"  {row['home']} vs {row['away']}: "
                f"HOME {row['home_odds']} DRAW {row['draw_odds']} AWAY {row['away_odds']}"
            )
        _out_path("http_1x2_sample.json").write_text(
            json.dumps(decrypt["sample"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"ok": True, "summary": summary, "decrypt": decrypt}
    print(f"Decrypt/parse failed: {decrypt.get('reason')}")
    return {"ok": False, "summary": summary, "decrypt": decrypt}


def approach_chromium(url: str) -> dict:
    print("==================================================")
    print("APPROACH 2 — local persistent Chromium (no ZenRows)")
    print("==================================================")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"Playwright not importable: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": "playwright_missing"}

    profile = _out_path("chromium-profile")
    profile.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
                user_agent=USER_AGENT,
                locale="tr-TR",
            )
            page = context.pages[0] if context.pages else context.new_page()
            print(f"Opening {PREMATCH_PAGE}")
            page.goto(PREMATCH_PAGE, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            print("Fetching endpoint from the page context (cookies included)...")
            result = page.evaluate(
                """async (target) => {
                    const response = await fetch(target, { credentials: "include" });
                    const text = await response.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch (e) { json = null; }
                    return {
                        status: response.status,
                        contentType: response.headers.get("content-type"),
                        textPrefix: text.slice(0, 180),
                        payload: (json && (json.payload || json.Payload)) || null,
                        jsonKeys: json && typeof json === "object" ? Object.keys(json).slice(0, 20) : [],
                        bodyLength: text.length,
                    };
                }""",
                url,
            )
            context.close()
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    print(
        f"page fetch HTTP {result.get('status')} "
        f"keys={result.get('jsonKeys')} bytes={result.get('bodyLength')}"
    )
    _out_path("chromium_meta.json").write_text(
        json.dumps(
            {k: v for k, v in result.items() if k != "payload"},
            indent=2,
        ),
        encoding="utf-8",
    )
    payload = result.get("payload")
    if isinstance(payload, str) and len(payload) > 20:
        _out_path("chromium_encrypted.txt").write_text(payload, encoding="utf-8")
        decrypt = _try_decrypt(payload)
        if decrypt.get("ok"):
            print(
                f"DECRYPT OK events={decrypt['structure'].get('events')} "
                f"valid_1x2={decrypt['event_count']}"
            )
            for row in decrypt["sample"][:5]:
                print(
                    f"  {row['home']} vs {row['away']}: "
                    f"HOME {row['home_odds']} DRAW {row['draw_odds']} AWAY {row['away_odds']}"
                )
            return {"ok": True, "result": {k: v for k, v in result.items() if k != "payload"}, "decrypt": decrypt}
        print(f"Decrypt/parse failed: {decrypt.get('reason')}")
        return {"ok": False, "result": {k: v for k, v in result.items() if k != "payload"}, "decrypt": decrypt}
    print("No encrypted payload in page fetch.")
    return {"ok": False, "result": {k: v for k, v in result.items() if k != "payload"}}


def approach_session_notes(http_result: dict, chromium_result: dict) -> None:
    print("==================================================")
    print("APPROACH 3 — session requirements (both previous failed)")
    print("==================================================")
    http_summary = (http_result or {}).get("summary") or {}
    print(f"HTTP status: {http_summary.get('status')}")
    print(f"HTTP html challenge: {http_summary.get('looks_like_html')}")
    print(f"HTTP payload_kind: {http_summary.get('payload_kind')}")
    if chromium_result:
        print(f"Chromium error/status: {chromium_result.get('error') or (chromium_result.get('result') or {}).get('status')}")
    print(
        "Likely requirement if both failed: cookies from betkanyon1617.com "
        "and/or sport.bksp3.com after a real page load, plus Origin/Referer. "
        "ZenRows was providing that browser session, not necessarily unique IP."
    )


def main() -> int:
    print()
    print("BetKanyon prematch DIRECT ACCESS experiment")
    print(f"Started {datetime.now(timezone.utc).isoformat()}")
    print(f"Temp output: {OUT_DIR}")
    print("ZenRows: NOT USED")
    print()
    url = build_prematch_url(TOURNAMENT_ID)
    http_result = approach_http(url)
    chromium_result = None
    if http_result.get("ok"):
        print()
        print("RESULT: direct HTTP succeeded. Local Chromium not required.")
        print("Existing scanner/ZenRows code was not modified.")
        return 0
    chromium_result = approach_chromium(url)
    if chromium_result.get("ok"):
        print()
        print("RESULT: local Chromium page-fetch succeeded. ZenRows CDP not required.")
        print("Existing scanner/ZenRows code was not modified.")
        return 0
    approach_session_notes(http_result, chromium_result)
    print()
    print("RESULT: neither direct HTTP nor local Chromium produced a decryptable payload.")
    print("Existing scanner/ZenRows code was not modified.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
