import asyncio
import logging
import threading

import pytest
from fastapi.testclient import TestClient

from framegen.api import app as app_module
from framegen.api.app import create_app
from framegen.health import Check, Readiness


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


def test_default_checks_are_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[int] = []

    def fake_default_checks(settings: object) -> dict[str, Check]:
        built.append(1)
        return {"storage": ok}

    monkeypatch.setattr(app_module, "default_checks", fake_default_checks)
    with TestClient(create_app()) as client:
        assert built == [1], "built at startup"
        client.get("/v1/health/ready")
        client.get("/v1/health/ready")
    assert built == [1]


def test_bad_settings_stop_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_default_checks(settings: object) -> dict[str, Check]:
        raise ValueError("bad storage address")

    monkeypatch.setattr(app_module, "default_checks", broken_default_checks)
    with pytest.raises(ValueError, match="bad storage address"), TestClient(create_app()):
        pass


def test_a_check_that_dies_unexpectedly_does_not_wedge_readiness() -> None:
    calls: list[int] = []

    def dies() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise SystemExit("library gave up")  # not an Exception subclass

    readiness = Readiness({"storage": dies}, deadline=1)
    assert asyncio.run(readiness.run()) == {"storage": "unavailable"}
    assert asyncio.run(readiness.run()) == {"storage": "ok"}


def test_a_hung_check_is_cut_off_and_does_not_hold_up_others() -> None:
    release = threading.Event()
    started: list[int] = []

    def hung() -> None:
        started.append(1)
        release.wait(5)

    readiness = Readiness({"storage": hung, "database": ok}, deadline=0.1)
    try:
        for _ in range(3):
            assert asyncio.run(readiness.run()) == {"storage": "unavailable", "database": "ok"}
        assert started == [1], "a check still running must not be started again"
    finally:
        release.set()


def test_failure_is_logged_once_until_it_changes(caplog: pytest.LogCaptureFixture) -> None:
    state = {"up": False}

    def flaky() -> None:
        if not state["up"]:
            raise ConnectionError("down")

    readiness = Readiness({"storage": flaky})
    with caplog.at_level(logging.INFO, logger="framegen.health"):
        asyncio.run(readiness.run())
        asyncio.run(readiness.run())
        state["up"] = True
        asyncio.run(readiness.run())
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "readiness check 'storage' failed: ConnectionError: down",
        "readiness check 'storage' recovered",
    ]
