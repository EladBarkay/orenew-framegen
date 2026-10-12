"""Following a job through its server-sent events, with a real worker, against Postgres."""

import asyncio
import json
import socket
import threading
import time
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from framegen.api.app import create_app
from framegen.api.auth import SESSION_COOKIE
from framegen.settings import Settings
from framegen.worker.main import run as run_worker


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(readiness_checks={}, settings=settings)) as test_client:
        yield test_client
    asyncio.run(run_worker(settings, wait=False))


@pytest.fixture(scope="module")
def server(settings: Settings) -> Iterator[str]:
    """The API served by uvicorn, as the TestClient does not stream responses."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(
        create_app(readiness_checks={}, settings=settings), port=port, log_level="warning"
    )
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run)
    thread.start()
    while not running.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join()


def sign_up(client: TestClient) -> str:
    client.cookies.clear()
    client.post(
        "/v1/auth/signup",
        json={
            "email": f"events-{uuid.uuid4().hex[:12]}@example.com",
            "password": "correct horse battery",
            "name": "Events",
        },
    )
    workspace_id: str = client.get("/v1/workspaces").json()["items"][0]["id"]
    return workspace_id


def read_events(
    client: TestClient, server: str, path: str, settings: Settings
) -> tuple[list[Any], str]:
    """Reads the whole stream from a real server, while a worker runs the job."""
    worker = threading.Thread(target=lambda: asyncio.run(run_worker(settings, wait=False)))
    cookie = f"{SESSION_COOKIE}={client.cookies.get(SESSION_COOKIE)}"
    request = urllib.request.Request(server + path, headers={"Cookie": cookie})
    jobs: list[Any] = []
    with urllib.request.urlopen(request, timeout=30) as response:
        content_type = response.headers["Content-Type"]
        worker.start()
        for raw in response:
            line = raw.decode().rstrip("\n")
            if line.startswith("data: "):
                jobs.append(json.loads(line.removeprefix("data: ")))
    worker.join()
    return jobs, content_type


def test_a_job_is_followed_to_its_end(client: TestClient, server: str, settings: Settings) -> None:
    workspace_id = sign_up(client)
    job = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={"steps": 3}).json()
    path = f"/v1/workspaces/{workspace_id}/jobs/{job['id']}/events"
    jobs, content_type = read_events(client, server, path, settings)

    assert content_type.startswith("text/event-stream")
    assert jobs[0]["status"] == "queued"
    assert jobs[-1]["status"] == "succeeded"
    assert jobs[-1]["result"] == {"steps": 3}
    progress = [j["progress"] for j in jobs]
    assert progress == sorted(progress)
    assert any(j["status"] == "running" and 0 < j["progress"] < 1 for j in jobs)


def test_a_finished_job_sends_one_event_and_ends(
    client: TestClient, server: str, settings: Settings
) -> None:
    workspace_id = sign_up(client)
    job = client.post(
        f"/v1/workspaces/{workspace_id}/jobs/demo",
        json={"steps": 2, "fail_with": "demo_failed"},
    ).json()
    asyncio.run(run_worker(settings, wait=False))
    path = f"/v1/workspaces/{workspace_id}/jobs/{job['id']}/events"
    jobs, _ = read_events(client, server, path, settings)
    assert [(j["status"], j["error"]["code"]) for j in jobs] == [("failed", "demo_failed")]


def test_another_workspace_cannot_follow_a_job(client: TestClient) -> None:
    workspace_id = sign_up(client)
    job = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={}).json()
    mine = sign_up(client)
    response = client.get(f"/v1/workspaces/{mine}/jobs/{job['id']}/events")
    assert response.status_code == 404


def test_a_reconnect_to_an_ended_job_is_told_to_stop(
    client: TestClient, settings: Settings
) -> None:
    workspace_id = sign_up(client)
    job = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={"steps": 1}).json()
    asyncio.run(run_worker(settings, wait=False))
    path = f"/v1/workspaces/{workspace_id}/jobs/{job['id']}/events"
    response = client.get(path, headers={"Last-Event-ID": "3"})
    assert response.status_code == 204


def test_events_are_numbered(client: TestClient, server: str, settings: Settings) -> None:
    workspace_id = sign_up(client)
    job = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={"steps": 2}).json()
    cookie = f"{SESSION_COOKIE}={client.cookies.get(SESSION_COOKIE)}"
    request = urllib.request.Request(
        f"{server}/v1/workspaces/{workspace_id}/jobs/{job['id']}/events",
        headers={"Cookie": cookie},
    )
    worker = threading.Thread(target=lambda: asyncio.run(run_worker(settings, wait=False)))
    with urllib.request.urlopen(request, timeout=30) as response:
        worker.start()
        ids = [raw.decode().strip() for raw in response if raw.startswith(b"id: ")]
    worker.join()
    assert ids == [f"id: {n}" for n in range(1, len(ids) + 1)]
    assert len(ids) >= 2
