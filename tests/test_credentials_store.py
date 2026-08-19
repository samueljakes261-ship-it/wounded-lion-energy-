"""
Tests for credentials/store.py: loading/saving the encrypted
credential store and its runtime-state companion file, and the
"missing store file" / "env:" reference behaviors.
"""
import pytest

from credentials.crypto import generate_master_key
from credentials.errors import CredentialStoreError
from credentials.models import CredentialRuntimeState, StoredCredential
from credentials.store import CredentialStore


def make_store(tmp_path):
    return CredentialStore(
        store_path=str(tmp_path / "credentials.json"),
        state_path=str(tmp_path / "runtime" / "credentials_state.json"),
    )


def test_missing_credential_file_raises(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(CredentialStoreError):
        store.load_credentials()


def test_ensure_store_exists_creates_empty_store(tmp_path):
    store = make_store(tmp_path)
    store.ensure_store_exists()

    assert store.load_credentials() == []


def test_save_and_load_credentials_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", generate_master_key())
    store = make_store(tmp_path)

    encrypted = CredentialStore.encrypt("wss://browser.zenrows.com?apikey=abc123")
    credential = StoredCredential(
        credential_id="zenrows-01",
        provider="zenrows",
        encrypted_secret=encrypted,
        enabled=True,
        label="primary",
    )

    store.save_credentials([credential])

    loaded = store.load_credentials()
    assert len(loaded) == 1
    assert loaded[0].credential_id == "zenrows-01"
    assert loaded[0].provider == "zenrows"

    # The file on disk must never contain the plaintext secret.
    raw_contents = (tmp_path / "credentials.json").read_text(encoding="utf-8")
    assert "abc123" not in raw_contents

    assert store.decrypt(loaded[0]) == "wss://browser.zenrows.com?apikey=abc123"


def test_env_reference_secret_is_read_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_TEST_SECRET_VAR", "value-from-env")
    store = make_store(tmp_path)

    credential = StoredCredential(
        credential_id="zenrows-env",
        provider="zenrows",
        encrypted_secret="env:SOME_TEST_SECRET_VAR",
    )

    assert store.decrypt(credential) == "value-from-env"


def test_env_reference_missing_variable_raises(tmp_path):
    store = make_store(tmp_path)

    credential = StoredCredential(
        credential_id="zenrows-env",
        provider="zenrows",
        encrypted_secret="env:SOME_VAR_THAT_DOES_NOT_EXIST",
    )

    with pytest.raises(CredentialStoreError):
        store.decrypt(credential)


def test_runtime_state_round_trip(tmp_path):
    store = make_store(tmp_path)

    state = {
        "zenrows-01": CredentialRuntimeState(
            status="healthy", consecutive_failures=0,
        )
    }
    store.save_state(state)

    loaded = store.load_state()
    assert loaded["zenrows-01"].status == "healthy"


def test_load_state_with_no_file_returns_empty_dict(tmp_path):
    store = make_store(tmp_path)
    assert store.load_state() == {}


def test_reset_state_deletes_state_file_but_not_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", generate_master_key())
    store = make_store(tmp_path)

    store.save_credentials([
        StoredCredential(
            credential_id="zenrows-01",
            provider="zenrows",
            encrypted_secret=CredentialStore.encrypt("secret"),
        )
    ])
    store.save_state({"zenrows-01": CredentialRuntimeState(status="healthy")})

    store.reset_state()

    assert store.load_state() == {}
    # Credentials must survive a state reset untouched.
    assert len(store.load_credentials()) == 1
