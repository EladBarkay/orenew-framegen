import logging
import threading

import pytest
from fastapi.testclient import TestClient

from framegen.api.app import create_app
from framegen.health import Readiness


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


def test_checks_are_built_once_and_reused() -> None:
    calls: list[str] = []
    client = TestClient(create_app(readiness_checks={"storage": lambda: calls.append("x")}))
    client.get("/v1/health/ready")
    client.get("/v1/health/ready")
    assert calls == ["x", "x"]


def test_a_hung_check_is_cut_off_at_the_deadline() -> None:
    release = threading.Event()

    def hung() -> None:
        release.wait(5)

    readiness = Readiness({"storage": hung, "database": ok}, 0.1)
    try:
        assert readiness.run() == {"storage": "unavailable", "database": "ok"}
    finally:
        release.set()


def test_failure_is_logged_once_until_it_changes(caplog: pytest.LogCaptureFixture) -> None:
    state = {"up": False}

    def flaky() -> None:
        if not state["up"]:
            raise ConnectionError("down")

    readiness = Readiness({"storage": flaky})
    with caplog.at_level(logging.INFO, logger="framegen.health"):
        readiness.run()
        readiness.run()
        state["up"] = True
        readiness.run()
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "readiness check 'storage' failed: ConnectionError: down",
        "readiness check 'storage' recovered",
    ]
