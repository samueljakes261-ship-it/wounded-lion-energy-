"""
Symmetric encryption for the credential store, using Fernet
(AES-128-CBC + HMAC, authenticated) from the `cryptography` package.

The master key (MASTER_CREDENTIAL_KEY) lives only in the environment
(.env locally; an injected env var / secret manager on a VPS) and is
NEVER written to the credential store, a log line, or an error message.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

from credentials.errors import CredentialStoreError

MASTER_KEY_ENV_VAR = "MASTER_CREDENTIAL_KEY"


def generate_master_key() -> str:
    """Generate a new random Fernet key, suitable for MASTER_CREDENTIAL_KEY."""
    return Fernet.generate_key().decode("utf-8")


def _load_fernet(master_key: str = None) -> Fernet:
    key = master_key if master_key is not None else os.getenv(MASTER_KEY_ENV_VAR)

    if not key:
        raise CredentialStoreError(
            f"{MASTER_KEY_ENV_VAR} is not set. Generate one with "
            f"'python -m credentials.cli init' and add it to your .env file."
        )

    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise CredentialStoreError(
            f"{MASTER_KEY_ENV_VAR} is not a valid Fernet key."
        ) from exc


def encrypt_secret(plaintext: str, master_key: str = None) -> str:
    fernet = _load_fernet(master_key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str, master_key: str = None) -> str:
    fernet = _load_fernet(master_key)

    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialStoreError(
            "Failed to decrypt credential -- MASTER_CREDENTIAL_KEY does not "
            "match the key used to encrypt the store (or the store is "
            "corrupted)."
        ) from exc
