"""
Tests for credentials/crypto.py: encryption round-trip, missing key,
and invalid/mismatched master key handling.

No network, no real credentials -- everything uses freshly generated
Fernet keys.
"""
import pytest

from credentials.crypto import (
    decrypt_secret,
    encrypt_secret,
    generate_master_key,
)
from credentials.errors import CredentialStoreError


def test_encrypt_decrypt_round_trip():
    key = generate_master_key()
    plaintext = "wss://browser.zenrows.com?apikey=super-secret-value"

    token = encrypt_secret(plaintext, master_key=key)

    assert token != plaintext
    assert plaintext not in token

    assert decrypt_secret(token, master_key=key) == plaintext


def test_decrypt_with_wrong_master_key_raises():
    key_a = generate_master_key()
    key_b = generate_master_key()

    token = encrypt_secret("some-secret", master_key=key_a)

    with pytest.raises(CredentialStoreError):
        decrypt_secret(token, master_key=key_b)


def test_missing_master_key_raises(monkeypatch):
    monkeypatch.delenv("MASTER_CREDENTIAL_KEY", raising=False)

    with pytest.raises(CredentialStoreError):
        encrypt_secret("some-secret")


def test_invalid_master_key_format_raises():
    with pytest.raises(CredentialStoreError):
        encrypt_secret("some-secret", master_key="not-a-valid-fernet-key")


def test_master_key_read_from_environment(monkeypatch):
    key = generate_master_key()
    monkeypatch.setenv("MASTER_CREDENTIAL_KEY", key)

    token = encrypt_secret("plaintext-value")
    assert decrypt_secret(token) == "plaintext-value"
