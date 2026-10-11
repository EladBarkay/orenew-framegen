import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from framegen.api.app import create_app
from framegen.api.errors import ApiError
from framegen.api.idempotency import (
    KEPT_FOR,
    LOCK_TIMEOUT,
    InProgress,
    MemoryIdempotencyStore,
    Started,
)


class Order(BaseModel):
    size: int


def app_counting_calls(calls: list[int], store: MemoryIdempotencyStore) -> FastAPI:
    app = create_app(readiness_checks={}, idempotency_store=store)

    @app.post("/v1/orders", status_code=201)
    def create(order: Order) -> dict[str, int]:
        calls.append(order.size)
        return {"id": len(calls), "size": order.size}

    @app.post("/v1/flaky")
    def flaky() -> None:
        calls.append(0)
        raise ApiError(503, "storage_unavailable", "Try again.")

    return app


def test_a_repeated_request_gets_the_first_answer_without_running_again() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        first = client.post("/v1/orders", json={"size": 3}, headers={"Idempotency-Key": "k1"})
        again = client.post("/v1/orders", json={"size": 3}, headers={"Idempotency-Key": "k1"})
    assert calls == [3]
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json() == {"id": 1, "size": 3}
    assert again.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers


def test_without_a_key_every_request_runs() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        client.post("/v1/orders", json={"size": 1})
        client.post("/v1/orders", json={"size": 1})
    assert calls == [1, 1]


def test_reusing_a_key_for_another_request_is_refused() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        client.post("/v1/orders", json={"size": 1}, headers={"Idempotency-Key": "k"})
        response = client.post("/v1/orders", json={"size": 2}, headers={"Idempotency-Key": "k"})
    assert calls == [1]
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"


def test_server_errors_are_not_remembered() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        client.post("/v1/flaky", headers={"Idempotency-Key": "k"})
        client.post("/v1/flaky", headers={"Idempotency-Key": "k"})
    assert calls == [0, 0]


def test_a_repeat_while_the_first_still_runs_is_refused() -> None:
    store = MemoryIdempotencyStore()
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, store)) as client:
        body = b'{"size":5}'
        # Another process has started this request and not finished it yet.
        from framegen.api.idempotency import fingerprint

        asyncio.run(
            store.begin(
                "anonymous", "k", fingerprint("POST", "/v1/orders", b"", body), datetime.now(UTC)
            )
        )
        response = client.post(
            "/v1/orders",
            content=body,
            headers={"Idempotency-Key": "k", "Content-Type": "application/json"},
        )
    assert calls == []
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_key_in_progress"


def test_an_invalid_key_is_refused() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        response = client.post(
            "/v1/orders", json={"size": 1}, headers={"Idempotency-Key": "x" * 256}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"
    assert calls == []


def test_reads_ignore_the_key() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        response = client.get("/v1/health", headers={"Idempotency-Key": "k"})
    assert response.status_code == 200
    assert "Idempotent-Replayed" not in response.headers


def test_store_rules_for_expiry_and_crashed_requests() -> None:
    store = MemoryIdempotencyStore()
    now = datetime.now(UTC)

    async def scenario() -> None:
        assert await store.begin("s", "k", "f", now) == Started()
        assert await store.begin("s", "k", "f", now + timedelta(seconds=1)) == InProgress()
        # The first run never finished (crashed): a repeat may run after the lock times out.
        assert await store.begin("s", "k", "f", now + LOCK_TIMEOUT) == Started()
        # After the key expires it is new again, even for another request.
        assert await store.begin("s", "k", "other", now + KEPT_FOR + LOCK_TIMEOUT) == Started()

    asyncio.run(scenario())
