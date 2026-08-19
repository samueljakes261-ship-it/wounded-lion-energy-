"""
Integration tests for credentials/zenrows_provider.py's
connect_with_failover(): success path, failover between credentials,
bounded retries for transient errors, "all unavailable", and -- most
importantly -- that a secret embedded in a connection error message
never leaks into logs or the raised exception.

Uses a fake Playwright object (no real browser, no network, no real
credentials).
"""
import logging

import pytest

import credentials.manager as manager_module
from credentials.crypto import generate_master_key
from credentials.errors import AllCredentialsUnavailableError, TransientProviderConnectError
from credentials.manager import CredentialManager
from credentials.models import StoredCredential
from credentials.store import CredentialStore
from credentials.zenrows_provider import connect_with_failover
import credentials.zenrows_provider as zenrows_provider


SECRET_A = "wss://browser.zenrows.com?apikey=SECRET-VALUE-CREDENTIAL-A"
SECRET_B = "wss://browser.zenrows.com?apikey=SECRET-VALUE-CREDENTIAL-B"


class FakeBrowser:
    pass


class FakeChromium:
    """Simulates playwright.chromium.connect_over_cdp(browser_ws)."""

    def __init__(self, script):
        # script: dict mapping browser_ws -> list of results, where a
        # result is either a callable() to call, or the string
        # "SUCCESS" to return a FakeBrowser.
        self.script = script
        self.calls = []

    def connect_over_cdp(self, browser_ws):
        self.calls.append(browser_ws)
        key = browser_ws
        if key not in self.script:
            key = zenrows_provider.ws_without_session_ttl(browser_ws)
        outcomes = self.script[key]
        outcome = outcomes.pop(0)

        if outcome == "SUCCESS":
            return FakeBrowser()

        raise outcome


class FakePlaywright:
    def __init__(self, script):
        self.chromium = FakeChromium(script)


@pytest.fixture(autouse=True)
def _isolated_manager(tmp_path, monkeypatch):
    """
    Point the module-level manager singleton at a fresh, isolated
    store for every test, and make sure the legacy env fallback never
    interferes.
    """
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", generate_master_key())
    monkeypatch.delenv("ZENROWS_BROWSER_WS", raising=False)

    store = CredentialStore(
        store_path=str(tmp_path / "credentials.json"),
        state_path=str(tmp_path / "runtime" / "credentials_state.json"),
    )
    store.ensure_store_exists()

    manager = CredentialManager("zenrows", store=store)

    # get_manager()/connect_with_failover() both go through the
    # process-wide singleton dict in credentials.manager -- patch THAT
    # (not a same-named attribute on zenrows_provider, which is a
    # different object and would not actually be consulted) so this
    # test's isolated store is what's actually used, and so it's
    # cleanly restored afterwards regardless of test order.
    monkeypatch.setattr(manager_module, "_managers", {"zenrows": manager})

    # Don't actually sleep during retry-backoff in tests.
    monkeypatch.setattr(zenrows_provider.time, "sleep", lambda seconds: None)

    yield manager


def add_credential(manager, credential_id, secret):
    creds = manager.store.load_credentials()
    creds.append(
        StoredCredential(
            credential_id=credential_id,
            provider="zenrows",
            encrypted_secret=CredentialStore.encrypt(secret),
        )
    )
    manager.store.save_credentials(creds)


def test_successful_connect_reports_success(_isolated_manager):
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)

    playwright = FakePlaywright({SECRET_A: ["SUCCESS"]})

    browser, credential_id = connect_with_failover(playwright)

    assert isinstance(browser, FakeBrowser)
    assert credential_id == "zenrows-01"
    assert all("session_ttl=15m" in call for call in playwright.chromium.calls)
    assert all("SECRET-VALUE-CREDENTIAL-A" in call for call in playwright.chromium.calls)

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "healthy"


def test_invalid_credential_fails_over_to_next(_isolated_manager):
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)
    add_credential(manager, "zenrows-02", SECRET_B)

    auth_error = Exception(f"401 Unauthorized AUTH003 invalid api key for {SECRET_A}")

    playwright = FakePlaywright({
        SECRET_A: [auth_error],
        SECRET_B: ["SUCCESS"],
    })

    browser, credential_id = connect_with_failover(playwright)

    assert credential_id == "zenrows-02"

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "disabled"
    assert descriptions["zenrows-02"]["status"] == "healthy"


def test_transient_error_retries_same_credential_before_moving_on(_isolated_manager):
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)
    add_credential(manager, "zenrows-02", SECRET_B)

    network_error = Exception(f"Connection refused connecting to {SECRET_A}")

    # MAX_RETRIES_PER_CREDENTIAL attempts on zenrows-01, all failing,
    # then the pool moves on to zenrows-02.
    attempts_on_a = [network_error] * zenrows_provider.MAX_RETRIES_PER_CREDENTIAL

    playwright = FakePlaywright({
        SECRET_A: list(attempts_on_a),
        SECRET_B: ["SUCCESS"],
    })

    browser, credential_id = connect_with_failover(playwright)

    assert credential_id == "zenrows-02"
    assert len(playwright.chromium.calls) == zenrows_provider.MAX_RETRIES_PER_CREDENTIAL + 1
    assert all("session_ttl=15m" in call for call in playwright.chromium.calls)

    # A transient network error must NOT disable the credential --
    # rotating away from it is a last resort for this attempt only.
    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "cooling_down"


def test_all_credentials_unavailable_raises_without_leaking_secret(_isolated_manager, caplog):
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)

    auth_error = Exception(f"401 Unauthorized AUTH003 invalid api key ({SECRET_A})")

    playwright = FakePlaywright({
        SECRET_A: [auth_error],
    })

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AllCredentialsUnavailableError) as excinfo:
            connect_with_failover(playwright)

    assert SECRET_A not in str(excinfo.value)

    for record in caplog.records:
        assert SECRET_A not in record.getMessage()
        assert "apikey=" not in record.getMessage()


def test_bounded_retries_never_loop_forever(_isolated_manager):
    """
    Every credential permanently fails -- connect_with_failover must
    terminate (not hang/loop forever) and raise a clear error.
    """
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)
    add_credential(manager, "zenrows-02", SECRET_B)

    server_error = Exception("503 Service Unavailable")

    playwright = FakePlaywright({
        SECRET_A: [server_error] * zenrows_provider.MAX_RETRIES_PER_CREDENTIAL,
        SECRET_B: [server_error] * zenrows_provider.MAX_RETRIES_PER_CREDENTIAL,
    })

    with pytest.raises(AllCredentialsUnavailableError):
        connect_with_failover(playwright)

    # Exactly MAX_RETRIES_PER_CREDENTIAL attempts per credential, no more.
    calls_a = [c for c in playwright.chromium.calls if "SECRET-VALUE-CREDENTIAL-A" in c]
    calls_b = [c for c in playwright.chromium.calls if "SECRET-VALUE-CREDENTIAL-B" in c]
    assert len(calls_a) == zenrows_provider.MAX_RETRIES_PER_CREDENTIAL
    assert len(calls_b) == zenrows_provider.MAX_RETRIES_PER_CREDENTIAL
    assert all("session_ttl=15m" in c for c in playwright.chromium.calls)


def test_target_closed_does_not_mark_quota_or_disable(_isolated_manager):
    """
    A remote browser dying (Session TTL / TargetClosedError) must be
    retried on the SAME credential. It is not QUOTA_EXHAUSTED and must
    not disable the key.
    """
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)
    add_credential(manager, "zenrows-02", SECRET_B)

    closed = Exception(
        "TargetClosedError: Page.wait_for_timeout: "
        "Target page, context or browser has been closed"
    )
    playwright = FakePlaywright({
        SECRET_A: [closed] * zenrows_provider.MAX_RETRIES_PER_CREDENTIAL,
        SECRET_B: ["SUCCESS"],
    })

    browser, credential_id = connect_with_failover(playwright)

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] != "disabled"
    assert descriptions["zenrows-01"]["failure_type"] != "QUOTA_EXHAUSTED"
    assert descriptions["zenrows-01"]["failure_type"] != "AUTHENTICATION_FAILURE"


def test_quota_exhausted_still_failovers(_isolated_manager):
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)
    add_credential(manager, "zenrows-02", SECRET_B)

    quota = Exception("402 Payment Required AUTH004 usage exceeded")
    playwright = FakePlaywright({
        SECRET_A: [quota],
        SECRET_B: ["SUCCESS"],
    })

    browser, credential_id = connect_with_failover(playwright)

    assert credential_id == "zenrows-02"
    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["failure_type"] == "QUOTA_EXHAUSTED"


def test_apply_persistent_session_ttl_never_logs_secret(caplog):
    raw = SECRET_A
    with caplog.at_level(logging.DEBUG):
        once = zenrows_provider.apply_persistent_session_ttl(raw)
        twice = zenrows_provider.apply_persistent_session_ttl(once)

    assert "session_ttl=15m" in once
    assert once == twice
    assert "SECRET-VALUE-CREDENTIAL-A" in once
    for record in caplog.records:
        assert SECRET_A not in record.getMessage()
        assert "apikey=" not in record.getMessage()


def test_single_credential_transient_failure_does_not_empty_the_pool(_isolated_manager):
    """
    One ZenRows key + network/TargetClosed failures must NOT raise
    AllCredentialsUnavailableError (that made OnWin look idle while
    the only key was still valid). The worker retries the same key.
    """
    manager = _isolated_manager
    add_credential(manager, "zenrows-01", SECRET_A)

    network_error = Exception("Target page, context or browser has been closed")
    playwright = FakePlaywright({
        SECRET_A: [network_error] * zenrows_provider.MAX_RETRIES_PER_CREDENTIAL,
    })

    with pytest.raises(TransientProviderConnectError) as excinfo:
        connect_with_failover(playwright)

    assert SECRET_A not in str(excinfo.value)
    assert "apikey=" not in str(excinfo.value).lower()

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] != "disabled"
    assert descriptions["zenrows-01"]["failure_type"] != "QUOTA_EXHAUSTED"

