"""
Tests for credentials/failures.py: classify_zenrows_error() must map
realistic ZenRows/Playwright error messages to the right FailureType,
and every error type is decisive (either failover-worthy or not).
"""
import pytest

from credentials.failures import (
    FAILOVER_TYPES,
    RETRY_SAME_CREDENTIAL_TYPES,
    FailureType,
    classify_zenrows_error,
)


class FakeError(Exception):
    pass


@pytest.mark.parametrize("message,expected", [
    ("Error: 401 Unauthorized - invalid api key (AUTH003)", FailureType.INVALID_CREDENTIAL),
    ("connect_over_cdp: 402 Payment Required - AUTH004 usage exceeded", FailureType.QUOTA_EXHAUSTED),
    ("connect_over_cdp: 402 Payment Required", FailureType.RATE_LIMITED),
    ("401 Unauthorized", FailureType.AUTHENTICATION_FAILURE),
    ("429 Too Many Requests - rate limit exceeded", FailureType.RATE_LIMITED),
    ("502 Bad Gateway", FailureType.SERVER_ERROR),
    ("503 Service Unavailable", FailureType.SERVER_ERROR),
    ("Timeout 30000ms exceeded while connecting", FailureType.NETWORK_ERROR),
    ("getaddrinfo failed: Name or service not known", FailureType.NETWORK_ERROR),
    ("Connection refused", FailureType.NETWORK_ERROR),
    ("TargetClosedError: Page.wait_for_timeout: Target page, context or browser has been closed", FailureType.NETWORK_ERROR),
    ("session expired: session ttl", FailureType.NETWORK_ERROR),
    ("400 Bad Request - malformed query parameter", FailureType.REQUEST_ERROR),
    ("service temporarily unavailable, please try again", FailureType.TEMPORARY_PROVIDER_ERROR),
    ("something completely unrecognized happened", FailureType.UNKNOWN_ERROR),
])
def test_classification_mapping(message, expected):
    assert classify_zenrows_error(FakeError(message)) == expected


def test_timeout_error_type_name_is_classified_as_network():
    # Playwright raises playwright._impl._errors.TimeoutError for a
    # connect_over_cdp() timeout with a message that doesn't always
    # contain the word "timeout" itself -- the exception TYPE name
    # should still be enough to classify it correctly.
    assert classify_zenrows_error(TimeoutError("connection did not complete")) == FailureType.NETWORK_ERROR


def test_every_failure_type_is_categorized_exactly_once():
    all_types = set(FailureType)
    categorized = FAILOVER_TYPES | RETRY_SAME_CREDENTIAL_TYPES

    assert categorized == all_types
    assert FAILOVER_TYPES.isdisjoint(RETRY_SAME_CREDENTIAL_TYPES)


def test_target_closed_error_type_is_network_not_failover():
    class TargetClosedError(Exception):
        pass

    assert classify_zenrows_error(TargetClosedError("page closed")) == FailureType.NETWORK_ERROR
    assert FailureType.NETWORK_ERROR not in FAILOVER_TYPES
    assert FailureType.QUOTA_EXHAUSTED in FAILOVER_TYPES
