"""
Data models for the credential store.

StoredCredential is what lives in credentials.json (secret encrypted).
CredentialRuntimeState is what lives in the runtime-state file --
non-secret health metadata only, safe to delete/reset at any time.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StoredCredential:
    """
    One entry in the encrypted credential store.

    `encrypted_secret` is either:
      - a Fernet token produced by credentials.crypto.encrypt_secret(), or
      - "env:SOME_ENV_VAR" to reference a secret supplied purely via an
        environment variable (useful for VPS secret-injection setups,
        and used internally for the legacy single-key fallback).

    It is NEVER a plaintext secret.
    """
    credential_id: str
    provider: str
    encrypted_secret: str
    enabled: bool = True
    created_at: str = field(default_factory=utcnow_iso)
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "credential_id": self.credential_id,
            "provider": self.provider,
            "encrypted_secret": self.encrypted_secret,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "label": self.label,
        }

    @staticmethod
    def from_dict(data: dict) -> "StoredCredential":
        return StoredCredential(
            credential_id=data["credential_id"],
            provider=data["provider"],
            encrypted_secret=data["encrypted_secret"],
            enabled=bool(data.get("enabled", True)),
            created_at=data.get("created_at") or utcnow_iso(),
            label=data.get("label", ""),
        )


@dataclass
class CredentialRuntimeState:
    """
    Safe (non-secret) runtime health metadata for one credential.

    status is one of: "unknown", "healthy", "cooling_down", "disabled".
    """
    status: str = "unknown"
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    failure_type: Optional[str] = None
    consecutive_failures: int = 0
    cooldown_until: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "failure_type": self.failure_type,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_until": self.cooldown_until,
        }

    @staticmethod
    def from_dict(data: dict) -> "CredentialRuntimeState":
        return CredentialRuntimeState(
            status=data.get("status", "unknown"),
            last_success=data.get("last_success"),
            last_failure=data.get("last_failure"),
            failure_type=data.get("failure_type"),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            cooldown_until=data.get("cooldown_until"),
        )
