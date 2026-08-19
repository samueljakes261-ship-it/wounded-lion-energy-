"""
Failure classification for credential-backed providers.

The point of this module is to make sure we do NOT treat every error
the same way. Rotating credentials only makes sense for a handful of
failure types (bad/revoked credential, provider-approved quota
exhaustion); everything else should be retried in place with bounded
backoff, exactly like the rest of this project already does at the
worker level.
"""
from enum import Enum


class FailureType(str, Enum):
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    INVALID_CREDENTIAL = "INVALID_CREDENTIAL"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARY_PROVIDER_ERROR = "TEMPORARY_PROVIDER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    REQUEST_ERROR = "REQUEST_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# Failure types where trying a DIFFERENT authorized credential is
# actually justified: the current credential itself is the problem.
FAILOVER_TYPES = frozenset({
    FailureType.AUTHENTICATION_FAILURE,
    FailureType.INVALID_CREDENTIAL,
    FailureType.QUOTA_EXHAUSTED,
})

# Failure types where the credential is fine and rotating would not
# help -- these should be retried on the SAME credential with bounded
# backoff instead. RATE_LIMITED in particular must never trigger
# rotation: that would look like evading the provider's rate limit.
RETRY_SAME_CREDENTIAL_TYPES = frozenset({
    FailureType.RATE_LIMITED,
    FailureType.TEMPORARY_PROVIDER_ERROR,
    FailureType.NETWORK_ERROR,
    FailureType.SERVER_ERROR,
    FailureType.REQUEST_ERROR,
    FailureType.UNKNOWN_ERROR,
})


def classify_zenrows_error(exc: BaseException) -> FailureType:
    """
    Best-effort classification of an exception raised while connecting
    to ZenRows' Scraping Browser (Playwright connect_over_cdp against
    the ZenRows browser_ws endpoint).

    ZenRows surfaces provider error codes as part of the WebSocket/CDP
    handshake failure text (e.g. "...402...AUTH004...usage exceeded...",
    "...401...AUTH003...invalid api key..."), so we pattern-match on
    the stringified exception rather than parsing structured JSON.

    IMPORTANT: the caller must never log or re-raise `exc` itself (or
    its str()) beyond this function -- ZenRows connection errors can
    echo the connection URL, which embeds the API key. Only the
    resulting FailureType (and, at most, type(exc).__name__) are safe
    to log.
    """
    message = str(exc).lower()
    name = type(exc).__name__.lower()

    def has(*needles):
        return any(needle in message for needle in needles)

    if has("auth003", "invalid api key", "invalid_api_key", "invalid apikey"):
        return FailureType.INVALID_CREDENTIAL

    if has("auth004", "usage exceeded", "quota exceeded", "quota_exceeded",
           "plan limit exceeded", "monthly limit exceeded", "credits exceeded"):
        return FailureType.QUOTA_EXHAUSTED

    if has("401", "unauthorized") or (has("auth0") and "auth004" not in message):
        return FailureType.AUTHENTICATION_FAILURE

    if has("402", "payment required"):
        # A bare 402 without AUTH004/usage-exceeded is often a
        # concurrent-session limit, not monthly quota. Treating it as
        # QUOTA_EXHAUSTED applied a 1-hour cooldown to the shared
        # ZenRows key and blocked BetKanyon reconnect after a live
        # session's TargetClosed death. AUTH004 still matches above.
        return FailureType.RATE_LIMITED

    if has("429", "too many requests", "rate limit", "rate_limit"):
        return FailureType.RATE_LIMITED

    if has("500", "502", "503", "504", "internal server error",
           "bad gateway", "service unavailable", "gateway timeout"):
        return FailureType.SERVER_ERROR

    if has("timeout", "timed out") or "timeout" in name:
        return FailureType.NETWORK_ERROR

    if has("targetclosederror", "target page", "browser has been closed",
           "context has been closed", "session expired", "session ttl"):
        # Remote browser session ended (idle/TTL). Retry the SAME
        # credential -- this is not quota exhaustion.
        return FailureType.NETWORK_ERROR

    if has("connection refused", "connection reset", "name or service not known",
           "getaddrinfo failed", "econnrefused", "network is unreachable",
           "ssl", "handshake", "socket") or "targetclosed" in name:
        return FailureType.NETWORK_ERROR

    if has("400", "bad request", "malformed"):
        return FailureType.REQUEST_ERROR

    if has("temporarily unavailable", "try again"):
        return FailureType.TEMPORARY_PROVIDER_ERROR

    return FailureType.UNKNOWN_ERROR
