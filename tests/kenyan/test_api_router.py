"""
Tests for kenyan/api_router.py, calling the route handler functions
directly (rather than through FastAPI's TestClient / starlette
TestClient) because this environment's `starlette.testclient` module
currently requires a package that is not part of this project's own
`requirements.txt` (a pre-existing, unrelated environment gap --
`tests/test_deployment_cors_and_contract.py` already hits the exact
same problem on the existing Turkish/client-facing API, confirmed by
running the full existing suite before making any Kenyan changes).

NOTE: the access-code gate that previously sat in front of
/kenyan/opportunities and /kenyan/status was removed at explicit user
request (the "KENYAN BOOKMAKERS" nav link now goes straight to the
opportunities view). kenyan/access.py itself is untouched and still
independently tested by test_access.py in case the gate is
re-attached later -- these tests now cover the current, public
behavior of the two routes.
"""
from kenyan.api_router import opportunities, status
from kenyan.runner import KenyanEngineRunner, get_runner


def test_opportunities_endpoint_is_publicly_accessible(monkeypatch):
    """
    No access code / session / Authorization header is required --
    calling the route handler directly, with nothing else set up,
    must not raise or require any prior authorization step.
    """
    fresh_runner = KenyanEngineRunner()  # never started -- no real network activity
    monkeypatch.setattr("kenyan.api_router.get_runner", lambda: fresh_runner)

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
