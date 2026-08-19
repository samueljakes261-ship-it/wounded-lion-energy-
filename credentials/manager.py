"""
CredentialManager: selection, health tracking, cooldown, and failover
for one provider's pool of authorized credentials.

This module never logs or raises an exception containing a decrypted
secret, an Authorization header, or the master key -- only
credential_id values and failure classifications.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from credentials.errors import (
    AllCredentialsUnavailableError,
    NoCredentialsConfiguredError,
)
from credentials.failures import FAILOVER_TYPES, FailureType
from credentials.models import CredentialRuntimeState, StoredCredential
from credentials.store import CredentialStore

logger = logging.getLogger("credentials")

# Consecutive AUTHENTICATION_FAILURE failures after which a credential
# is disabled outright rather than merely cooled down.
# INVALID_CREDENTIAL is always disabled immediately (never transient).
DISABLE_AFTER_CONSECUTIVE_FAILURES = 3

# Backoff used for cooldowns, doubling per consecutive failure up to a
# cap -- mirrors the exponential backoff already used at the worker
# level elsewhere in this project (see parsers/betkanyon/worker.py).
BASE_COOLDOWN_SECONDS = 30
MAX_COOLDOWN_SECONDS = 3600

# Persistent ZenRows sessions last up to 15 minutes. A second collector
# (OnWin) failing to open a concurrent CDP session must not mark the
# shared key QUOTA_EXHAUSTED for an hour while BetKanyon's already-open
# session is still healthy -- otherwise BetKanyon cannot reconnect when
# its page later dies (TargetClosed).
RECENT_SUCCESS_GRACE_SECONDS = 20 * 60

# Legacy single-credential fallback: if no credentials are configured
# in the encrypted store for a provider, but the provider's historical
# .env variable is set, synthesize one in-memory credential from it so
# existing setups keep working with zero migration required.
_LEGACY_ENV_VARS = {
    "zenrows": "ZENROWS_BROWSER_WS",
}

_managers = {}


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _legacy_env_credential(provider):
    env_var = _LEGACY_ENV_VARS.get(provider)

    if not env_var or not os.getenv(env_var):
        return None

    return StoredCredential(
        credential_id=f"{provider}-env-legacy",
        provider=provider,
        encrypted_secret=f"env:{env_var}",
        enabled=True,
        label="Legacy single-credential fallback (.env, not in encrypted store)",
    )


class CredentialManager:
    """
    Owns credential selection/failover for exactly one provider (e.g.
    "zenrows"). Reloads from disk on every call rather than caching
    indefinitely, since OnWin/BetKanyon run in separate processes/
    threads and the on-disk state file is their shared source of truth.
    """

    def __init__(self, provider: str, store: CredentialStore = None):
        self.provider = provider
        self.store = store or CredentialStore()

    # -- loading ------------------------------------------------------

    def _load(self):
        all_credentials = self.store.load_credentials_if_exists()

        credentials = [c for c in all_credentials if c.provider == self.provider]

        if not credentials:
            legacy = _legacy_env_credential(self.provider)
            if legacy is not None:
                credentials = [legacy]

        state = self.store.load_state()

        for c in credentials:
            state.setdefault(c.credential_id, CredentialRuntimeState())

        return credentials, state

    def _save_state(self, state):
        self.store.save_state(state)

    # -- selection ------------------------------------------------------

    @staticmethod
    def _is_available(credential: StoredCredential, state: CredentialRuntimeState, now) -> bool:
        if not credential.enabled:
            return False

        if state.status == "disabled":
            return False

        cooldown_until = _parse_iso(state.cooldown_until)

        if cooldown_until and now < cooldown_until:
            return False

        return True

    def list_available(self, exclude: set = None):
        exclude = exclude or set()
        credentials, state = self._load()
        now = _now()

        return [
            c for c in credentials
            if c.credential_id not in exclude
            and self._is_available(c, state[c.credential_id], now)
        ]

    def select(self, exclude: set = None):
        """
        Return the StoredCredential to try next, or None if nothing
        authorized is currently available.
        """
        exclude = exclude or set()
        credentials, state = self._load()
        now = _now()

        candidates = [
            c for c in credentials
            if c.credential_id not in exclude
            and self._is_available(c, state[c.credential_id], now)
        ]

        if not candidates:
            return None

        # Prefer whichever available credential succeeded most
        # recently (keeps traffic on a warm/known-good credential
        # instead of bouncing between them for no reason).
        def sort_key(c):
            last_success = _parse_iso(state[c.credential_id].last_success)
            return last_success or datetime.min.replace(tzinfo=timezone.utc)

        candidates.sort(key=sort_key, reverse=True)
        chosen = candidates[0]

        logger.info(
            "[CredentialManager] %s selected (provider=%s)",
            chosen.credential_id, self.provider,
        )

        return chosen

    def seconds_until_available(self, exclude: set = None):
        """
        Seconds until at least one authorized credential becomes
        selectable, or 0 if one is already available.

        Returns None if every credential is disabled (will not recover
        without a manual enable/reset).
        """
        exclude = exclude or set()
        credentials, state = self._load()
        now = _now()
        soonest = None

        for credential in credentials:
            if credential.credential_id in exclude:
                continue
            if self._is_available(credential, state[credential.credential_id], now):
                return 0.0

            runtime = state[credential.credential_id]
            if not credential.enabled or runtime.status == "disabled":
                continue

            cooldown_until = _parse_iso(runtime.cooldown_until)
            if cooldown_until and cooldown_until > now:
                remaining = (cooldown_until - now).total_seconds()
                if soonest is None or remaining < soonest:
                    soonest = remaining

        return soonest

    def get_active_secret(self, exclude: set = None):
        """
        Return (credential_id, decrypted_secret) for the currently
        selected credential.

        Raises NoCredentialsConfiguredError if nothing is configured at
        all, or AllCredentialsUnavailableError if everything configured
        is currently disabled/cooling down.
        """
        credentials, _ = self._load()

        if not credentials:
            raise NoCredentialsConfiguredError(
                f"No credentials configured for provider '{self.provider}'. "
                f"Run 'python -m credentials.cli add --provider {self.provider} "
                f"--secret ...'."
            )

        chosen = self.select(exclude)

        if chosen is None:
            retry_after = self.seconds_until_available(exclude)
            logger.warning(
                "[CredentialManager] all authorized credentials unavailable "
                "(provider=%s, retry_after=%s)",
                self.provider,
                None if retry_after is None else f"{retry_after:.0f}s",
            )
            raise AllCredentialsUnavailableError(
                f"All authorized credentials for provider '{self.provider}' "
                f"are currently unavailable (disabled or cooling down).",
                retry_after_seconds=retry_after,
            )

        secret = self.store.decrypt(chosen)
        return chosen.credential_id, secret

    # -- health reporting ------------------------------------------------

    def report_success(self, credential_id: str):
        _, state = self._load()

        if credential_id not in state:
            return

        s = state[credential_id]
        s.status = "healthy"
        s.last_success = _now().isoformat()
        s.failure_type = None
        s.consecutive_failures = 0
        s.cooldown_until = None

        self._save_state(state)

        logger.info(
            "[CredentialManager] %s reported success (provider=%s)",
            credential_id, self.provider,
        )

    def report_failure(self, credential_id: str, failure_type: FailureType, detail: str = None) -> bool:
        """
        Record a failure for one credential and decide what happens to
        it.

        Returns True if the caller should attempt another authorized
        credential for this logical operation, False if it should
        retry the SAME credential (bounded, with its own backoff)
        instead.

        `detail` must be short and non-sensitive (e.g. an exception
        type name) -- never the raw exception message, request/response
        body, or headers, since ZenRows connection errors can echo the
        connection URL (which embeds the API key).
        """
        _, state = self._load()

        if credential_id not in state:
            return False

        s = state[credential_id]

        last_ok = _parse_iso(s.last_success)
        recently_worked = (
            last_ok is not None
            and (_now() - last_ok).total_seconds() < RECENT_SUCCESS_GRACE_SECONDS
        )
        # A second collector failing to open a concurrent ZenRows
        # session must not lock the shared key while another collector
        # already proved it works. Only INVALID/AUTH mean the key
        # itself is the problem.
        if recently_worked and failure_type not in (
            FailureType.INVALID_CREDENTIAL,
            FailureType.AUTHENTICATION_FAILURE,
        ):
            age = (_now() - last_ok).total_seconds()
            logger.info(
                "[CredentialManager] %s %s ignored -- credential succeeded "
                "%.0fs ago (concurrent session, not disabling) [%s]",
                credential_id, failure_type.value, age, detail or "",
            )
            s.last_failure = _now().isoformat()
            s.failure_type = failure_type.value
            self._save_state(state)
            return False

        s.last_failure = _now().isoformat()
        s.failure_type = failure_type.value
        s.consecutive_failures += 1

        should_failover = failure_type in FAILOVER_TYPES
        suffix = f" [{detail}]" if detail else ""

        if failure_type == FailureType.INVALID_CREDENTIAL:
            # Never transient -- an invalid credential will not become
            # valid again on its own. Disable until manually restored.
            s.status = "disabled"
            s.cooldown_until = None
            logger.warning(
                "[CredentialManager] %s invalid credential -- disabled "
                "(provider=%s)%s", credential_id, self.provider, suffix,
            )

        elif failure_type == FailureType.AUTHENTICATION_FAILURE:
            if s.consecutive_failures >= DISABLE_AFTER_CONSECUTIVE_FAILURES:
                s.status = "disabled"
                s.cooldown_until = None
                logger.warning(
                    "[CredentialManager] %s disabled after %d consecutive "
                    "authentication failures (provider=%s)%s",
                    credential_id, s.consecutive_failures, self.provider, suffix,
                )
            else:
                cooldown = _backoff_seconds(s.consecutive_failures)
                s.status = "cooling_down"
                s.cooldown_until = (_now() + timedelta(seconds=cooldown)).isoformat()
                logger.warning(
                    "[CredentialManager] %s authentication failure "
                    "(provider=%s, cooldown=%ds)%s",
                    credential_id, self.provider, cooldown, suffix,
                )

        elif failure_type == FailureType.QUOTA_EXHAUSTED:
            # Provider-approved quota exhaustion: quota resets are
            # provider-controlled and typically far slower than a
            # transient-error backoff, so use the maximum cooldown
            # instead of hammering a provider that already said "no
            # more requests right now".
            s.status = "cooling_down"
            s.cooldown_until = (_now() + timedelta(seconds=MAX_COOLDOWN_SECONDS)).isoformat()
            logger.warning(
                "[CredentialManager] %s quota exhausted (provider=%s, "
                "cooldown=%ds)%s",
                credential_id, self.provider, MAX_COOLDOWN_SECONDS, suffix,
            )

        elif failure_type == FailureType.RATE_LIMITED:
            # Respect the provider's own rate limit -- cool down the
            # SAME credential, never rotate to dodge it.
            cooldown = _backoff_seconds(s.consecutive_failures)
            s.status = "cooling_down"
            s.cooldown_until = (_now() + timedelta(seconds=cooldown)).isoformat()
            logger.info(
                "[CredentialManager] %s rate limited (provider=%s, "
                "cooldown=%ds)%s",
                credential_id, self.provider, cooldown, suffix,
            )

        else:
            # TEMPORARY_PROVIDER_ERROR / NETWORK_ERROR / SERVER_ERROR /
            # REQUEST_ERROR / UNKNOWN_ERROR: transient -- bounded
            # backoff on the SAME credential. Rotating would not fix a
            # network/server issue, and failing safe on unknown errors
            # avoids disabling something that might still be fine.
            cooldown = _backoff_seconds(s.consecutive_failures)
            s.status = "cooling_down"
            s.cooldown_until = (_now() + timedelta(seconds=cooldown)).isoformat()
            logger.info(
                "[CredentialManager] %s %s (provider=%s, cooldown=%ds)%s",
                credential_id, failure_type.value, self.provider, cooldown, suffix,
            )

        self._save_state(state)
        return should_failover

    # -- introspection (health checks / CLI) -----------------------------

    def describe_all(self):
        credentials, state = self._load()
        now = _now()

        return [
            {
                "credential_id": c.credential_id,
                "provider": c.provider,
                "label": c.label,
                "enabled": c.enabled,
                "available": self._is_available(c, state[c.credential_id], now),
                **state[c.credential_id].to_dict(),
            }
            for c in credentials
        ]

    def has_any_configured(self) -> bool:
        credentials, _ = self._load()
        return len(credentials) > 0

    def reset_runtime_state(self):
        """
        Clear persisted runtime state for this provider's credentials
        (used by reset-dev/reset-prod). Never touches the encrypted
        secrets themselves.
        """
        credentials, state = self._load()

        for c in credentials:
            state[c.credential_id] = CredentialRuntimeState()

        self._save_state(state)


def _backoff_seconds(consecutive_failures: int) -> int:
    exponent = max(0, min(consecutive_failures - 1, 6))
    return min(BASE_COOLDOWN_SECONDS * (2 ** exponent), MAX_COOLDOWN_SECONDS)


def get_manager(provider: str) -> CredentialManager:
    """Process-wide convenience singleton per provider."""
    if provider not in _managers:
        _managers[provider] = CredentialManager(provider)
    return _managers[provider]
