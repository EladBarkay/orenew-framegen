"""Starting and following jobs through the API, with a real worker, against Postgres."""

import asyncio
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from framegen.api.app import create_app
from framegen.settings import Settings
from framegen.worker.main import run as run_worker


def sign_up(client: TestClient) -> str:
    """Signs a new user in; returns their personal workspace's ID."""
    client.cookies.clear()
    response = client.post(
        "/v1/auth/signup",
        json={
            "email": f"jobs-{uuid.uuid4().hex[:12]}@example.com",
            "password": "correct horse battery",
            "name": "Jobs",
        },
    )
    assert response.status_code == 201
    workspace_id: str = client.get("/v1/workspaces").json()["items"][0]["id"]
    return workspace_id


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(readiness_checks={}, settings=settings)) as test_client:
        yield test_client
    # Run whatever a test left queued, so it does not run inside a later test.
    asyncio.run(run_worker(settings, wait=False))


def test_a_demo_job_is_followed_to_completion(client: TestClient, settings: Settings) -> None:
    workspace_id = sign_up(client)
    started = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={"steps": 3})
    assert started.status_code == 202
    job = started.json()
    assert job["id"].startswith("job_")
    assert (job["type"], job["status"], job["progress"]) == ("demo", "queued", 0)
    assert started.headers["Location"] == f"/v1/workspaces/{workspace_id}/jobs/{job['id']}"

    asyncio.run(run_worker(settings, wait=False))

    done = client.get(started.headers["Location"]).json()
    assert (done["status"], done["progress"], done["result"]) == ("succeeded", 1, {"steps": 3})
    assert done["error"] is None
    assert done["started_at"] and done["finished_at"]


def test_a_failed_job_says_why(client: TestClient, settings: Settings) -> None:
    workspace_id = sign_up(client)
    job = client.post(
        f"/v1/workspaces/{workspace_id}/jobs/demo",
        json={"steps": 2, "fail_with": "demo_failed"},
    ).json()
    asyncio.run(run_worker(settings, wait=False))
    done = client.get(f"/v1/workspaces/{workspace_id}/jobs/{job['id']}").json()
    assert done["status"] == "failed"
    assert done["error"]["code"] == "demo_failed"
    assert done["result"] is None


def test_another_workspace_cannot_see_a_job(client: TestClient) -> None:
    workspace_id = sign_up(client)
    job = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={}).json()
    mine = sign_up(client)
    for path in (
        f"/v1/workspaces/{workspace_id}/jobs/{job['id']}",
        f"/v1/workspaces/{mine}/jobs/{job['id']}",
    ):
        response = client.get(path)
        assert response.status_code == 404, path


def test_demo_job_limits(client: TestClient) -> None:
    workspace_id = sign_up(client)
    for body in (
        {"steps": 0},
        {"steps": 21},
        {"fail_with": "Not A Code"},
        {"fail_with": "internal"},
    ):
        response = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json=body)
        assert response.status_code == 422, body


def test_one_demo_job_at_a_time(client: TestClient, settings: Settings) -> None:
    workspace_id = sign_up(client)
    path = f"/v1/workspaces/{workspace_id}/jobs/demo"
    assert client.post(path, json={"steps": 1}).status_code == 202
    second = client.post(path, json={"steps": 1})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "demo_job_running"
    asyncio.run(run_worker(settings, wait=False))
    assert client.post(path, json={"steps": 1}).status_code == 202


class RefusingQueue:
    """Stands in for the queue's task when the queue is down."""

    async def defer_async(self, **arguments: object) -> None:
        raise ConnectionError("queue down")


def test_a_queue_that_cannot_take_the_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = sign_up(client)
    queue = client.app.state.queue  # type: ignore[attr-defined]
    monkeypatch.setattr(queue, "configure_task", lambda name: RefusingQueue())
    response = client.post(f"/v1/workspaces/{workspace_id}/jobs/demo", json={})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "queue_unavailable"
    job = client.get(f"/v1/workspaces/{workspace_id}/jobs/{error['detail']['job_id']}").json()
    assert (job["status"], job["error"]["code"]) == ("failed", "queue_unavailable")


def test_one_demo_job_even_when_requests_arrive_together(
    client: TestClient, settings: Settings
) -> None:
    workspace_id = sign_up(client)
    path = f"/v1/workspaces/{workspace_id}/jobs/demo"
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: client.post(path, json={}).status_code, range(8)))
    assert sorted(statuses) == [202] + [409] * 7
