"""
Shared ZenRows connection helper.

Obtains the active credential from CredentialManager, attempts to
connect Playwright's sync API to ZenRows' Scraping Browser over CDP,
classifies failures, and fails over to another authorized ZenRows
credential when appropriate. Both existing ZenRowsSession classes
(utils/zenrows_persistent.py and browser/sessions/zenrows.py) call
this instead of reading ZENROWS_BROWSER_WS directly, so nothing that
uses either class needs to know which credential is currently active.

SECURITY NOTE: Playwright's connect_over_cdp() can raise an exception
whose message echoes the connection URL -- which, for ZenRows, embeds
the API key as a query parameter. This module NEVER logs or re-raises
that raw exception (or its str()); only the resulting FailureType and
the exception's *type name* are ever surfaced.
"""
import logging
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from credentials.errors import (
    AllCredentialsUnavailableError,
    CredentialError,
    TransientProviderConnectError,
)
from credentials.failures import classify_zenrows_error
from credentials.manager import get_manager

logger = logging.getLogger("credentials")

PROVIDER = "zenrows"

# Bounded retries on the SAME credential for transient failures before
# moving on to another authorized credential (if any exists) -- so a
# single flaky attempt doesn't immediately burn through the whole
# pool, but a persistent transient issue still eventually gives
# another credential a turn instead of looping forever.
MAX_RETRIES_PER_CREDENTIAL = 2
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 30

# ZenRows' default Session TTL is 3 minutes. Persistent collectors
# (OnWin, BetKanyon) stay connected far longer than that; when the
# remote browser is killed, Playwright raises TargetClosedError and
# the collector looks idle/starting forever while it races the TTL
# during first-page capture. 15 minutes is the documented maximum.
# This is a provider session lifetime, not a local wait-timeout.
PERSISTENT_SESSION_TTL = "15m"
_SESSION_TTL_PARAM = "session_ttl"


def apply_persistent_session_ttl(browser_ws: str) -> str:
    """
    Ensure the ZenRows CDP URL requests the maximum documented
    session lifetime.

    Never logs `browser_ws` -- the URL embeds the API key.
    """
    parts = urlsplit(browser_ws)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key == _SESSION_TTL_PARAM for key, _value in pairs):
        pairs = list(pairs) + [(_SESSION_TTL_PARAM, PERSISTENT_SESSION_TTL)]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def ws_without_session_ttl(browser_ws: str) -> str:
    """Test helper: strip session_ttl so fake Playwright can look up the raw secret."""
    parts = urlsplit(browser_ws)
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != _SESSION_TTL_PARAM
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment)
    )


def connect_with_failover(playwright):
    """
    Returns (browser, credential_id) using the credential pool
    configured for provider "zenrows".

    Raises AllCredentialsUnavailableError if every authorized
    credential is unavailable, or a CredentialError subclass if the
    provider is misconfigured (e.g. no credentials at all, bad master
    key) -- retrying/failing over cannot fix that, so it is raised
    immediately instead of being retried.
    """
    manager = get_manager(PROVIDER)

    tried = set()
    last_error_type = None

    while True:
        try:
            credential_id, browser_ws = manager.get_active_secret(exclude=tried)
        except AllCredentialsUnavailableError:
            break

        backoff = INITIAL_BACKOFF_SECONDS
        moved_on = False

        connect_url = apply_persistent_session_ttl(browser_ws)

        for attempt in range(1, MAX_RETRIES_PER_CREDENTIAL + 1):
            try:
                browser = playwright.chromium.connect_over_cdp(connect_url)
                manager.report_success(credential_id)
                return browser, credential_id

            except Exception as exc:
                last_error_type = type(exc).__name__
                failure_type = classify_zenrows_error(exc)

                should_failover = manager.report_failure(
                    credential_id, failure_type, detail=type(exc).__name__
                )

                if should_failover:
                    # Authentication/invalid/quota -- another attempt
                    # on this same credential would not help.
                    moved_on = True
                    break

                if attempt >= MAX_RETRIES_PER_CREDENTIAL:
                    remaining = manager.list_available(
                        exclude=tried | {credential_id}
                    )
                    if remaining:
                        # Exhausted local retries for a transient error
                        # -- give another authorized credential a turn
                        # for THIS connection attempt without
                        # permanently disabling this one.
                        moved_on = True
                        break

                    if tried:
                        # Already tried every other credential this
                        # attempt -- the pool is exhausted for now.
                        moved_on = True
                        break

                    # Single-credential setup: do NOT pretend the
                    # whole pool is gone. The worker will backoff and
                    # retry this same key.
                    raise TransientProviderConnectError(
                        f"ZenRows connect failed after "
                        f"{MAX_RETRIES_PER_CREDENTIAL} retries "
                        f"({last_error_type})."
                    )

                logger.info(
                    "[CredentialManager] %s transient failure, retrying "
                    "in %ds (attempt %d/%d)",
                    credential_id, backoff, attempt, MAX_RETRIES_PER_CREDENTIAL,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

        if moved_on:
            tried.add(credential_id)

    logger.warning(
        "[CredentialManager] all authorized credentials unavailable "
        "(provider=%s)", PROVIDER,
    )
    retry_after = manager.seconds_until_available()
    detail = f" Last error type: {last_error_type}." if last_error_type else ""
    raise AllCredentialsUnavailableError(
        "All authorized ZenRows credentials are currently unavailable. "
        "Add/enable a credential or wait for cooldowns to expire." + detail,
        retry_after_seconds=retry_after,
    )
