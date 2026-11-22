"""Watch Onwin's own API calls. Does not invent headers or call ZenRows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from experiments.onwin_playwright.compare import compare_matches
from experiments.onwin_playwright.redact import (
    count_payload,
    fingerprint,
    header_summary,
    post_summary,
    safe_endpoint,
)
from experiments.onwin_playwright.session import MAIN_LINE, UPDATE_FRAGMENTS

OUTPUT = Path(__file__).resolve().parent / "output"


def _write_private(path: Path, text: str) -> None:
    """Write without chmod. Windows rejects chmod-altered files with Errno 22."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    try:
        temporary.replace(path)
    except OSError:
        path.write_text(text, encoding="utf-8", newline="\n")
        temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _interesting(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        "erisgaming" in lowered
        or "api-onwin" in lowered
        or "538.lol" in lowered
    )


def _is_main_line(url: str) -> bool:
    return MAIN_LINE in (url or "")


def _is_update(url: str) -> bool:
    lowered = (url or "").lower()
    return any(fragment in lowered for fragment in UPDATE_FRAGMENTS)


class OnwinObserver:
    def __init__(self):
        self.started_at = _now()
        self.browser_status = "starting"
        self.auth_status = "not_started"
        self.page_url = ""
        self.last_error = None
        self.last_api_at = None
        self.last_odds_at = None
        self.last_endpoint = None
        self.requests = 0
        self.main_line_responses = 0
        self.update_responses = 0
        self.events = 0
        self.markets = 0
        self.odds = 0
        self.parser_rows = 0
        self.x_token_present = False
        self.x_message_metadata_present = False
        self.token_fingerprints: list[str] = []
        self.metadata_fingerprints: list[str] = []
        self.token_refreshed = False
        self.metadata_refreshed = False
        self.parser_ok = False
        self.comparison = None
        self.page_title = ""
        self.hosts: list[str] = []
        self._seen_paths: set[str] = set()

    def note_page(self, url: str) -> None:
        endpoint = safe_endpoint(url)
        host = endpoint.get("host") or ""
        path = endpoint.get("path") or ""
        self.page_url = f"{host}{path}" if host else path
        self.note_host(host)
        if self.auth_status == "not_started":
            self.auth_status = "page_open"

    def note_title(self, title: str) -> None:
        self.page_title = (title or "")[:80]
        lowered = self.page_title.lower()
        if self.auth_status == "odds_captured":
            return
        if any(token in lowered for token in ("just a moment", "cloudflare", "attention required")):
            self.auth_status = "cloudflare_check"

    def note_host(self, host: str) -> bool:
        if not host or host in self.hosts or len(self.hosts) >= 20:
            return False
        self.hosts.append(host)
        return True

    def note_error(self, message: str) -> None:
        self.last_error = message[:300]

    def observe_request(self, method: str, url: str, headers: dict, post_data: str | None) -> dict | None:
        if not _interesting(url):
            return None
        endpoint = safe_endpoint(url)
        record = {
            "at": _now(),
            "method": method,
            "endpoint": endpoint,
            "headers": header_summary(headers),
            "post": post_summary(post_data),
        }
        self.requests += 1
        self.last_api_at = record["at"]
        self.last_endpoint = endpoint
        path = endpoint.get("path") or ""
        if path and path not in self._seen_paths and len(self._seen_paths) < 30:
            self._seen_paths.add(path)
        token = header_summary(headers).get("x-token") or {}
        metadata = header_summary(headers).get("x-message-metadata") or {}
        if token.get("present"):
            self.x_token_present = True
            self._remember("token", token.get("fingerprint"))
        if metadata.get("present"):
            self.x_message_metadata_present = True
            self._remember("metadata", metadata.get("fingerprint"))
        return record

    def _remember(self, kind: str, value: str | None) -> None:
        if not value:
            return
        store = self.token_fingerprints if kind == "token" else self.metadata_fingerprints
        if store and store[-1] == value:
            return
        if store:
            if kind == "token":
                self.token_refreshed = True
            else:
                self.metadata_refreshed = True
        store.append(value)

    def observe_response(self, url: str, status: int, content_type: str, body: bytes) -> dict | None:
        if not _interesting(url):
            return None
        record = {
            "at": _now(),
            "endpoint": safe_endpoint(url),
            "status": status,
            "content_type": content_type,
            "bytes": len(body or b""),
            "main_line": _is_main_line(url),
            "update": _is_update(url),
        }
        self.last_api_at = record["at"]
        if status != 200 or not body:
            record["parsed"] = False
            if status and status != 200:
                self.note_error(f"HTTP {status} {record['endpoint'].get('path')}")
            return record
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            record["parsed"] = False
            self.note_error("odds response was not JSON")
            return record
        counts = count_payload(payload)
        record["counts"] = {
            "shape": counts["shape"],
            "events": counts["events"],
            "markets": counts["markets"],
            "odds": counts["odds"],
        }
        if _is_update(url):
            self.update_responses += 1
        if not _is_main_line(url):
            return record
        self.main_line_responses += 1
        self.events = counts["events"]
        self.markets = counts["markets"]
        self.odds = counts["odds"]
        self.last_odds_at = record["at"]
        if counts["shape"] != "sports_tree":
            self.note_error(f"main-line shape {counts['shape']}")
            record["parser_rows"] = 0
            return record
        from parsers.onwin.parser import OnWinParser

        try:
            matches = OnWinParser().parse(payload)
        except Exception as exc:
            self.note_error(f"parser {type(exc).__name__}")
            record["parser_rows"] = 0
            return record
        self.parser_ok = True
        self.parser_rows = len(matches)
        record["parser_rows"] = len(matches)
        if matches:
            self.auth_status = "odds_captured"
            self.last_error = None
        elif self.auth_status != "odds_captured":
            self.auth_status = "response_without_live_1x2"
        self._matches = matches
        self._payload = payload
        return record

    def write_artifacts(self, production_snapshot: Path | None = None) -> None:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        payload = getattr(self, "_payload", None)
        if isinstance(payload, dict):
            _write_private(OUTPUT / "latest_get_main_line.json", json.dumps(payload))
        if production_snapshot and production_snapshot.exists() and getattr(self, "_matches", None) is not None:
            from parsers.onwin.parser import OnWinParser

            try:
                production = OnWinParser().parse(
                    json.loads(production_snapshot.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, TypeError):
                self.comparison = {"error": "production snapshot was not a main-line payload"}
            else:
                self.comparison = compare_matches(self._matches, production)
        status = self.status()
        text = json.dumps(status, indent=2)
        lowered = text.lower()
        if "x-token" in lowered and "fingerprint" not in lowered:
            raise RuntimeError("status would expose a token")
        path = OUTPUT / "status.json"
        _write_private(path, text)

    def status(self) -> dict:
        return {
            "browser_status": self.browser_status,
            "auth_status": self.auth_status,
            "page": self.page_url,
            "page_title": self.page_title,
            "hosts": list(self.hosts),
            "last_api_at": self.last_api_at,
            "last_odds_at": self.last_odds_at,
            "last_endpoint": self.last_endpoint,
            "last_error": self.last_error,
            "api_requests": self.requests,
            "main_line_responses": self.main_line_responses,
            "update_responses": self.update_responses,
            "events": self.events,
            "markets": self.markets,
            "odds": self.odds,
            "parser_rows": self.parser_rows,
            "parser_ok": self.parser_ok,
            "x_token_present": self.x_token_present,
            "x_message_metadata_present": self.x_message_metadata_present,
            "token_refreshed": self.token_refreshed,
            "metadata_refreshed": self.metadata_refreshed,
            "token_observations": len(self.token_fingerprints),
            "zenrows_used": False,
            "published_to_engine": False,
            "comparison": self.comparison,
            "seen_paths": sorted(self._seen_paths),
        }
