from fastapi.testclient import TestClient

from framegen import __version__
from framegen.api.app import create_app


def test_health_reports_ok_and_version() -> None:
    response = TestClient(create_app()).get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_openapi_is_served_under_v1() -> None:
    response = TestClient(create_app()).get("/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.1")


def test_openapi_states_licence_and_source() -> None:
    info = TestClient(create_app()).get("/v1/openapi.json").json()["info"]
    assert info["license"]["identifier"] == "AGPL-3.0-only"
    assert info["contact"]["url"] == "https://github.com/EladBarkay/orenew-framegen"
