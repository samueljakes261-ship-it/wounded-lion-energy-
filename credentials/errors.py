"""
Exception hierarchy for the credential management layer.

Kept small and specific so callers can distinguish "this is a
configuration problem" (CredentialStoreError) from "every authorized
credential is currently unusable" (AllCredentialsUnavailableError),
which need very different handling.
"""


class CredentialError(Exception):
    """Base class for all credential-management errors."""


class CredentialStoreError(CredentialError):
    """
    The encrypted credential store could not be loaded or decrypted.

    Examples: missing credentials.json, missing/invalid
    MASTER_CREDENTIAL_KEY, corrupted store file.
    """


class NoCredentialsConfiguredError(CredentialStoreError):
    """No credentials at all are configured for the requested provider."""


class AllCredentialsUnavailableError(CredentialError):
    """
    Every authorized credential for a provider is currently
    unavailable (disabled, cooling down, or failed during this
    attempt). This is a normal, expected outcome -- not a bug -- and
    callers should treat it as "the provider is temporarily/permanently
    unusable right now", not retry forever.

    `retry_after_seconds` is the soonest cooldown expiry (None if
    every credential is disabled and will not recover on its own).
    """

    def __init__(self, message="", retry_after_seconds=None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TransientProviderConnectError(CredentialError):
    """
    Connecting with the currently selected credential failed in a
    non-failover way (timeout, network, TargetClosed, etc.) and there
    is no other authorized credential to try. Callers should backoff
    and retry the SAME credential -- this is not quota exhaustion and
    must not disable the key.
    """
