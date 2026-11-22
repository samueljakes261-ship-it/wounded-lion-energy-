"""Run the local Onwin Playwright experiment.

From the repo root:

    python -m experiments.onwin_playwright.run

Chromium opens on this machine. Finish any Onwin or Cloudflare check in
that window. Odds stay in experiments/onwin_playwright/output/ and are
not sent to the engine. Ctrl+C closes the browser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from experiments.onwin_playwright.observe import OUTPUT, OnwinObserver
from experiments.onwin_playwright.redact import safe_endpoint
from experiments.onwin_playwright.session import launch_context, page_url

LOG = OUTPUT / "requests.jsonl"


def _log(message: str) -> None:
    print(f"[ONWIN PLAYWRIGHT] {message}", flush=True)


def _append(record: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _attach(context, observer: OnwinObserver) -> None:
    def on_request(request):
        host = safe_endpoint(request.url).get("host") or ""
        if observer.note_host(host):
            _log(f"host {host}")
        try:
            record = observer.observe_request(
                request.method,
                request.url,
                request.headers,
                request.post_data,
            )
        except Exception as exc:
            observer.note_error(f"request {type(exc).__name__}")
            return
        if record is not None:
            _append({"kind": "request", **record})
            endpoint = record["endpoint"]
            _log(f"{record['method']} {endpoint.get('host')}{endpoint.get('path')}")

    def on_finished(request):
        try:
            response = request.response()
            if response is None:
                return
            body = response.body()
            content_type = response.headers.get("content-type", "")
            record = observer.observe_response(
                request.url,
                response.status,
                content_type,
                body,
            )
        except Exception as exc:
            observer.note_error(f"response {type(exc).__name__}")
            return
        if record is None:
            return
        _append({"kind": "response", **record})
        if record.get("main_line"):
            _log(
                f"get_main_line status={record.get('status')} "
                f"bytes={record.get('bytes')} parser_rows={record.get('parser_rows')}"
            )

    context.on("request", on_request)
    context.on("requestfinished", on_finished)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Onwin local Playwright experiment")
    parser.add_argument(
        "--production-snapshot",
        type=Path,
        default=None,
        help="Existing get_main_line JSON to compare. Does not start ZenRows.",
    )
    args = parser.parse_args(argv)
    observer = OnwinObserver()
    _log(f"Opening {page_url()}")
    _log("ZenRows is not used. Complete any check in the browser window.")
    playwright = None
    context = None
    try:
        playwright, context = launch_context()
        observer.browser_status = "open"
        page = context.pages[0] if context.pages else context.new_page()
        _attach(context, observer)
        try:
            page.goto(page_url(), wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            observer.note_error(f"navigation {type(exc).__name__}")
            _log(f"Navigation did not finish ({type(exc).__name__}). The window stays open.")
        observer.note_page(page.url)
        observer.browser_status = "open"
        _log("Watching get_main_line.erisgaming. Ctrl+C stops the experiment.")
        while True:
            page.wait_for_timeout(5000)
            try:
                observer.note_page(page.url)
            except Exception as exc:
                observer.browser_status = "closed"
                observer.note_error(type(exc).__name__)
                break
            try:
                observer.note_title(page.title())
            except Exception:
                pass
            try:
                observer.write_artifacts(args.production_snapshot)
            except OSError as exc:
                observer.note_error(f"status file {type(exc).__name__}")
            status = observer.status()
            _log(
                "status "
                f"page={status['page'] or '-'} "
                f"title={status['page_title'] or '-'} "
                f"auth={status['auth_status']} "
                f"events={status['events']} "
                f"odds={status['odds']} "
                f"parser_rows={status['parser_rows']} "
                f"token={status['x_token_present']} "
                f"metadata={status['x_message_metadata_present']}"
            )
    except KeyboardInterrupt:
        _log("Stopped")
    finally:
        if observer.browser_status == "open":
            observer.browser_status = "closed"
        try:
            observer.write_artifacts(args.production_snapshot)
        except Exception as exc:
            _log(f"Could not write status ({type(exc).__name__})")
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
    result = "NOT_DEMONSTRATED"
    if observer.parser_rows > 0 and observer.main_line_responses >= 1:
        result = "CAPTURED_ONCE"
    if result == "CAPTURED_ONCE" and (
        observer.main_line_responses > 1 or observer.update_responses > 0
    ):
        result = "REPEATED"
    _log(f"EXPERIMENT_RESULT={result}")
    return 0 if result != "NOT_DEMONSTRATED" else 2


if __name__ == "__main__":
    sys.exit(main())
