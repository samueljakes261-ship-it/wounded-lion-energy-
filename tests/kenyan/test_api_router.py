"""
Tests for kenyan/api_router.py, calling the route handler functions
directly (rather than through FastAPI's TestClient / starlette
TestClient) because this environment's `starlette.testclient` module
currently requires a package that is not part of this project's own
`requirements.txt` (a pre-existing, unrelated environment gap --
`tests/test_deployment_cors_and_contract.py` already hits the exact
same problem on the existing Turkish/client-facing API, confirmed by
running the full existing suite before making any Kenyan changes).
Calling the handlers directly still fully exercises the real
auth/gating logic and is dependency-light, matching this module's own
"isolated, minimal dependencies" design.
"""
from fastapi import HTTPException
import pytest

from kenyan.api_router import (
    AccessCodeRequest,
    authenticate,
    opportunities,
    require_session,
    status,
)
from kenyan.runner import KenyanEngineRunner, get_runner


CORRECT_CODE = "23@2005"


def test_correct_code_returns_usable_token():
    response = authenticate(AccessCodeRequest(code=CORRECT_CODE))
    assert response.token
    assert response.expires_at > 0

    # The issued token itself must satisfy require_session.
    require_session(authorization=f"Bearer {response.token}")  # must not raise


def test_incorrect_code_is_rejected_with_generic_401():
    with pytest.raises(HTTPException) as exc_info:
        authenticate(AccessCodeRequest(code="wrong-code"))

    assert exc_info.value.status_code == 401
    # Never explains *why*, never echoes the submitted code.
    assert "wrong-code" not in str(exc_info.value.detail)
    assert CORRECT_CODE not in str(exc_info.value.detail)


def test_opportunities_endpoint_requires_a_session():
    """
    Kenyan opportunities must be inaccessible before authorization --
    calling the gated dependency with no/invalid token must raise 401.
    """
    with pytest.raises(HTTPException) as exc_info:
        require_session(authorization=None)
    assert exc_info.value.status_code == 401

    with pytest.raises(HTTPException):
        require_session(authorization="Bearer not-a-real-token")

    with pytest.raises(HTTPException):
        require_session(authorization="NotBearer sometoken")


def test_opportunities_endpoint_works_once_authorized(monkeypatch):
    fresh_runner = KenyanEngineRunner()  # never started -- no real network activity
    monkeypatch.setattr("kenyan.api_router.get_runner", lambda: fresh_runner)

    response = authenticate(AccessCodeRequest(code=CORRECT_CODE))
    require_session(authorization=f"Bearer {response.token}")  # gate passes

    live_result = opportunities(mode="live")
    prematch_result = opportunities(mode="prematch")

    assert live_result == []  # runner never started -> no opportunities, not an error
    assert prematch_result == []


def test_status_endpoint_reflects_runner_state(monkeypatch):
    fresh_runner = KenyanEngineRunner()
    monkeypatch.setattr("kenyan.api_router.get_runner", lambda: fresh_runner)

    result = status()
    assert result["started"] is False


def test_get_runner_is_a_singleton():
    assert get_runner() is get_runner()
