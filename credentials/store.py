"""
Encrypted credential store: a JSON file on disk holding one or more
providers' credentials, with each secret encrypted at rest, plus a
companion runtime-state file for non-secret health metadata.

Both files are plain JSON (easy to inspect/back up); only
`encrypted_secret` values are ever written to the credential file, and
the master key required to decrypt them never touches disk.
"""
import json
import os
import threading

from credentials.crypto import decrypt_secret, encrypt_secret
from credentials.errors import CredentialStoreError
from credentials.models import CredentialRuntimeState, StoredCredential

DEFAULT_STORE_PATH = os.getenv("CREDENTIALS_STORE_PATH", "credentials.json")
DEFAULT_STATE_PATH = os.getenv(
    "CREDENTIALS_STATE_PATH", os.path.join("runtime", "credentials_state.json")
)

_STORE_VERSION = 1

# Secrets referenced this way come straight from an environment
# variable instead of the encrypted store -- useful for VPS
# secret-injection setups, and used internally for the legacy
# single-key (.env-only) fallback.
_ENV_REF_PREFIX = "env:"


class CredentialStore:
    """Loads/saves credentials.json and its runtime-state companion."""

    def __init__(self, store_path: str = None, state_path: str = None):
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.state_path = state_path or DEFAULT_STATE_PATH
        self._lock = threading.Lock()

    # -- credentials.json -------------------------------------------------

    def load_credentials(self) -> list:
        if not os.path.exists(self.store_path):
            raise CredentialStoreError(
                f"Credential store not found at '{self.store_path}'. "
                f"Run 'python -m credentials.cli init' first."
            )

        with self._lock:
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except json.JSONDecodeError as exc:
                raise CredentialStoreError(
                    f"Credential store at '{self.store_path}' is not valid JSON."
                ) from exc

        entries = raw.get("credentials", [])
        return [StoredCredential.from_dict(e) for e in entries]

    def load_credentials_if_exists(self) -> list:
        """
        Like load_credentials(), but returns an empty list instead of
        raising when the store file simply doesn't exist yet (e.g.
        'init' has never been run). Still raises for a store file that
        exists but is corrupted/invalid.
        """
        if not os.path.exists(self.store_path):
            return []

        return self.load_credentials()

    def save_credentials(self, credentials: list) -> None:
        payload = {
            "version": _STORE_VERSION,
            "credentials": [c.to_dict() for c in credentials],
        }

        directory = os.path.dirname(os.path.abspath(self.store_path))
        os.makedirs(directory, exist_ok=True)

        with self._lock:
            tmp_path = f"{self.store_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.store_path)

    def ensure_store_exists(self) -> None:
        if not os.path.exists(self.store_path):
            self.save_credentials([])

    # -- runtime state ----------------------------------------------------

    def load_state(self) -> dict:
        if not os.path.exists(self.state_path):
            return {}

        with self._lock:
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}

        return {
            credential_id: CredentialRuntimeState.from_dict(data)
            for credential_id, data in raw.items()
        }

    def save_state(self, state: dict) -> None:
        directory = os.path.dirname(os.path.abspath(self.state_path))
        os.makedirs(directory, exist_ok=True)

        payload = {
            credential_id: s.to_dict() for credential_id, s in state.items()
        }

        with self._lock:
            tmp_path = f"{self.state_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self.state_path)

    def reset_state(self) -> None:
        """
        Delete the runtime-state file entirely (used by reset scripts).
        Never touches credentials.json (the encrypted secrets).
        """
        if os.path.exists(self.state_path):
            os.remove(self.state_path)

    # -- secrets ------------------------------------------------------

    def decrypt(self, credential: StoredCredential) -> str:
        if credential.encrypted_secret.startswith(_ENV_REF_PREFIX):
            env_var = credential.encrypted_secret[len(_ENV_REF_PREFIX):]
            value = os.getenv(env_var)

            if not value:
                raise CredentialStoreError(
                    f"Environment variable '{env_var}' referenced by "
                    f"credential '{credential.credential_id}' is not set."
                )

            return value

        return decrypt_secret(credential.encrypted_secret)

    @staticmethod
    def encrypt(plaintext: str) -> str:
        return encrypt_secret(plaintext)
