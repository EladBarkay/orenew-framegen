from fastapi.testclient import TestClient

from framegen.api.app import create_app


def ok() -> None:
    pass


def broken() -> None:
    raise ConnectionError("down")


def test_ready_when_every_check_passes() -> None:
    client = TestClient(create_app(readiness_checks={"database": ok, "storage": ok}))
    response = client.get("/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "storage": "ok"}}


def test_unavailable_names_the_failing_dependency() -> None:
    client = TestClient(create_app(readiness_checks={"database": ok, "storage": broken}))
    response = client.get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "storage": "unavailable"}
