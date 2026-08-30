"""
Verifies the integration point added to the existing api.py is purely
additive.

NOTE: `import api` itself currently fails in this environment due to a
PRE-EXISTING, unrelated bug -- api.py imports `get_collector_status`
from collector.py, but collector.py does not define that name. This
was confirmed to already exist on `main` before any Kenyan changes
(reverted this branch's changes and reproduced the identical
ImportError). It is not touched or fixed here, per the instruction to
leave existing working/non-working code alone -- so this test checks
api.py's SOURCE rather than importing it.
"""
from pathlib import Path

API_PY = Path(__file__).resolve().parents[2] / "api.py"


def test_existing_turkish_routes_are_all_still_present_unchanged():
    source = API_PY.read_text(encoding="utf-8")

    for expected in (
        '@app.get("/")',
        '@app.get("/health")',
        '@app.get("/opportunities")',
        '@app.get("/status")',
        "return get_cached_opportunities()",
        "return get_collector_status()",
    ):
        assert expected in source, f"existing Turkish route/behavior missing: {expected!r}"


def test_kenyan_integration_is_a_single_additive_call():
    source = API_PY.read_text(encoding="utf-8")

    assert "from kenyan.api_router import include_kenyan_routes" in source
    assert "include_kenyan_routes(app)" in source


def test_kenyan_router_never_reuses_turkish_route_paths():
    from kenyan.api_router import gated_router, router

    kenyan_paths = {route.path for route in router.routes} | {
        route.path for route in gated_router.routes
    }
    turkish_paths = {"/", "/health", "/opportunities", "/status"}

    assert kenyan_paths.isdisjoint(turkish_paths)
    assert all(path.startswith("/kenyan") for path in kenyan_paths)
