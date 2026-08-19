"""
Tests for credentials/manager.py: selection, failover, disabled/
cooldown skipping, retry protection semantics, "all unavailable",
correct failure-type handling, and the legacy .env fallback.

No network, no real credentials.
"""
from datetime import datetime, timedelta, timezone

import pytest

from credentials.crypto import generate_master_key
from credentials.errors import AllCredentialsUnavailableError, NoCredentialsConfiguredError
from credentials.failures import FailureType
from credentials.manager import CredentialManager
from credentials.models import StoredCredential
from credentials.store import CredentialStore


def make_manager(tmp_path, provider="zenrows"):
    store = CredentialStore(
        store_path=str(tmp_path / "credentials.json"),
        state_path=str(tmp_path / "runtime" / "credentials_state.json"),
    )
    store.ensure_store_exists()
    return CredentialManager(provider, store=store)


def add_credential(manager, credential_id, secret="wss://browser.zenrows.com?apikey=x", enabled=True, label=""):
    credentials = manager.store.load_credentials()
    credentials.append(
        StoredCredential(
            credential_id=credential_id,
            provider=manager.provider,
            encrypted_secret=CredentialStore.encrypt(secret),
            enabled=enabled,
            label=label,
        )
    )
    manager.store.save_credentials(credentials)


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", generate_master_key())
    # The legacy env fallback should never interfere with these tests.
    monkeypatch.delenv("ZENROWS_BROWSER_WS", raising=False)


def test_no_credentials_configured_raises(tmp_path):
    manager = make_manager(tmp_path)

    with pytest.raises(NoCredentialsConfiguredError):
        manager.get_active_secret()


def test_selects_the_only_healthy_credential(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    credential_id, secret = manager.get_active_secret()

    assert credential_id == "zenrows-01"
    assert secret == "wss://browser.zenrows.com?apikey=x"


def test_disabled_credential_is_skipped(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01", enabled=False)
    add_credential(manager, "zenrows-02")

    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-02"


def test_all_credentials_unavailable_raises_clear_error(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01", enabled=False)

    with pytest.raises(AllCredentialsUnavailableError):
        manager.get_active_secret()


def test_invalid_credential_failure_disables_immediately(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    add_credential(manager, "zenrows-02")

    should_failover = manager.report_failure(
        "zenrows-01", FailureType.INVALID_CREDENTIAL, detail="TestError"
    )

    assert should_failover is True

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "disabled"
    assert descriptions["zenrows-01"]["available"] is False

    # Failover: the other credential should now be selected.
    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-02"


def test_authentication_failure_disables_after_repeated_failures(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    for _ in range(2):
        manager.report_failure("zenrows-01", FailureType.AUTHENTICATION_FAILURE)

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "cooling_down"

    manager.report_failure("zenrows-01", FailureType.AUTHENTICATION_FAILURE)

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "disabled"


def test_quota_exhausted_fails_over_to_another_credential(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    add_credential(manager, "zenrows-02")

    should_failover = manager.report_failure("zenrows-01", FailureType.QUOTA_EXHAUSTED)
    assert should_failover is True

    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-02"

    # The exhausted credential must still be configured (not deleted),
    # just unavailable for now.
    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["available"] is False
    assert descriptions["zenrows-01"]["status"] == "cooling_down"


def test_rate_limited_does_not_trigger_failover(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    add_credential(manager, "zenrows-02")

    should_failover = manager.report_failure("zenrows-01", FailureType.RATE_LIMITED)

    # Rate limiting must be respected on the SAME credential, never
    # used as a reason to rotate (that would look like evasion).
    assert should_failover is False


def test_network_error_does_not_trigger_failover(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    should_failover = manager.report_failure("zenrows-01", FailureType.NETWORK_ERROR)
    assert should_failover is False


def test_cooldown_expires_and_credential_becomes_available_again(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    manager.report_failure("zenrows-01", FailureType.RATE_LIMITED)

    # Still within cooldown -- no credential should be selectable yet.
    with pytest.raises(AllCredentialsUnavailableError):
        manager.get_active_secret()

    # Simulate the cooldown having already expired by rewriting state
    # directly (avoids sleeping in a test).
    _, state = manager._load()
    state["zenrows-01"].cooldown_until = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    manager._save_state(state)

    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-01"


def test_report_success_clears_failure_state(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    manager.report_failure("zenrows-01", FailureType.NETWORK_ERROR)
    manager.report_success("zenrows-01")

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    d = descriptions["zenrows-01"]
    assert d["status"] == "healthy"
    assert d["consecutive_failures"] == 0
    assert d["cooldown_until"] is None


def test_prefers_most_recently_successful_credential(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    add_credential(manager, "zenrows-02")

    manager.report_success("zenrows-02")

    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-02"


def test_reset_runtime_state_clears_failures_but_keeps_credentials(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")

    manager.report_failure("zenrows-01", FailureType.AUTHENTICATION_FAILURE)
    manager.reset_runtime_state()

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["status"] == "unknown"
    assert descriptions["zenrows-01"]["consecutive_failures"] == 0

    # Credential itself (and its secret) must still exist.
    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-01"


def test_legacy_env_fallback_used_when_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENROWS_BROWSER_WS", "wss://browser.zenrows.com?apikey=legacy")

    manager = make_manager(tmp_path)  # no credentials.json entries at all

    credential_id, secret = manager.get_active_secret()

    assert credential_id == "zenrows-env-legacy"
    assert secret == "wss://browser.zenrows.com?apikey=legacy"


def test_legacy_env_fallback_not_used_when_store_has_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENROWS_BROWSER_WS", "wss://browser.zenrows.com?apikey=legacy")

    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01", secret="wss://browser.zenrows.com?apikey=configured")

    credential_id, secret = manager.get_active_secret()

    assert credential_id == "zenrows-01"
    assert secret == "wss://browser.zenrows.com?apikey=configured"


def test_recent_success_does_not_cooldown_on_concurrent_rate_limit(tmp_path):
    """A second collector's 402/rate-limit must not lock a key that
    just connected successfully (BetKanyon live session vs OnWin)."""
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    manager.report_success("zenrows-01")

    should_failover = manager.report_failure(
        "zenrows-01", FailureType.RATE_LIMITED, detail="Error",
    )

    assert should_failover is False
    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-01"

    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["available"] is True
    assert descriptions["zenrows-01"]["status"] == "healthy"
    assert descriptions["zenrows-01"]["consecutive_failures"] == 0


def test_recent_success_does_not_apply_hour_quota_cooldown(tmp_path):
    """A second concurrent CDP session returning 402/AUTH004 is not
    monthly quota if this key connected seconds ago."""
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    manager.report_success("zenrows-01")

    manager.report_failure("zenrows-01", FailureType.QUOTA_EXHAUSTED)

    credential_id, _ = manager.get_active_secret()
    assert credential_id == "zenrows-01"
    descriptions = {d["credential_id"]: d for d in manager.describe_all()}
    assert descriptions["zenrows-01"]["available"] is True
    assert descriptions["zenrows-01"]["status"] == "healthy"


def test_all_unavailable_error_includes_retry_after(tmp_path):
    manager = make_manager(tmp_path)
    add_credential(manager, "zenrows-01")
    manager.report_failure("zenrows-01", FailureType.RATE_LIMITED)

    with pytest.raises(AllCredentialsUnavailableError) as raised:
        manager.get_active_secret()

    assert raised.value.retry_after_seconds is not None
    assert raised.value.retry_after_seconds > 0
