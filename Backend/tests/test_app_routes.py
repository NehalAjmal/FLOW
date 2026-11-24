# Loads the real app (with the camera code stubbed out) and checks that the
# endpoints the Flutter app calls exist at /api/v1/... as well as at the bare path.
import sys
import types

import pytest

CONTRACT_PATHS = [
    ("GET", "/settings"), ("PUT", "/settings"), ("POST", "/pause"), ("DELETE", "/pause"),
    ("POST", "/intervention/{intervention_id}/respond"), ("POST", "/intervention/{intervention_id}/override"),
    ("POST", "/intervention/{intervention_id}/report"),
    ("POST", "/breaks/start"), ("POST", "/breaks/{break_id}/end"), ("GET", "/breaks"), ("POST", "/ratings"),
    ("GET", "/me/data-summary"), ("POST", "/me/data-export"), ("DELETE", "/me"),
    ("GET", "/sessions"), ("GET", "/session/{session_id}/replay"),
    ("GET", "/user/schedules"), ("POST", "/user/schedules"),
    ("GET", "/consent"),
    ("GET", "/user/dashboard"), ("GET", "/user/patterns"), ("GET", "/user/day"), ("GET", "/user/month"),
    ("GET", "/forecast"),
]


@pytest.fixture(scope="module")
def routes():
    stub = types.ModuleType("ml_models.fatigue_model")
    stub.fatigue_service = types.SimpleNamespace(get_state=lambda: {}, start=lambda: None, stop=lambda: None)
    sys.modules.setdefault("ml_models.fatigue_model", stub)
    main = pytest.importorskip("main")      # skips if an optional package (e.g. Google client) isn't installed
    return {(m, r.path) for r in main.app.routes for m in (getattr(r, "methods", None) or [])}


@pytest.mark.parametrize("method,path", CONTRACT_PATHS)
def test_route_exists_bare_and_under_api_v1(routes, method, path):
    assert (method, path) in routes
    assert (method, "/api/v1" + path) in routes
