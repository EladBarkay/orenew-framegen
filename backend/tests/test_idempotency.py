import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from framegen.api.app import create_app
from framegen.api.errors import ApiError
from framegen.api.idempotency import (
    KEPT_FOR,
    LOCK_TIMEOUT,
    InProgress,
    MemoryIdempotencyStore,
    PrincipalResolver,
    Replay,
    Started,
    StoredResponse,
    _Claim,
    wait_for_pending_keys,
)


class Order(BaseModel):
    size: int


def signed_in_as(principal: str | None) -> PrincipalResolver:
    async def resolve(scope: object) -> str | None:
        return principal

    return resolve


def app_counting_calls(calls: list[int], store: MemoryIdempotencyStore) -> FastAPI:
    app = create_app(
        readiness_checks={}, idempotency_store=store, principal_resolver=signed_in_as("tester")
    )

    @app.post("/v1/orders", status_code=201)
    def create(order: Order) -> dict[str, int]:
        calls.append(order.size)
        return {"id": len(calls), "size": order.size}

    @app.post("/v1/flaky")
    def flaky() -> None:
        calls.append(0)
        raise ApiError(503, "storage_unavailable", "Try again.")

    @app.delete("/v1/orders/{order_id}", status_code=204)
    def cancel(order_id: int) -> None:
        calls.append(order_id)

    @app.post("/v1/busy")
    def busy() -> None:
        calls.append(0)
        raise ApiError(429, "too_many_requests", "Slow down.")

    @app.post("/v1/stream")
    def stream() -> StreamingResponse:
        calls.append(0)

        async def parts() -> AsyncIterator[bytes]:
            for part in (b"one,", b"two,", b"three"):
                await asyncio.sleep(0.01)
                yield part

        return StreamingResponse(parts(), media_type="text/plain")

    @app.post("/v1/with-follow-up")
    def with_follow_up(tasks: BackgroundTasks) -> dict[str, bool]:
        calls.append(0)

        def follow_up() -> None:
            raise RuntimeError("follow-up failed")

        tasks.add_task(follow_up)
        return {"done": True}

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
                "tester", "k", fingerprint("POST", "/v1/orders", b"", body), datetime.now(UTC)
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


def test_retry_later_answers_are_not_remembered() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        client.post("/v1/busy", headers={"Idempotency-Key": "k"})
        response = client.post("/v1/busy", headers={"Idempotency-Key": "k"})
    assert calls == [0, 0]
    assert response.status_code == 429


def test_a_streamed_answer_arrives_whole_and_is_replayed() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        first = client.post("/v1/stream", headers={"Idempotency-Key": "k"})
        again = client.post("/v1/stream", headers={"Idempotency-Key": "k"})
    assert first.text == again.text == "one,two,three"
    assert calls == [0]


def test_a_failing_background_task_keeps_the_key_done() -> None:
    calls: list[int] = []
    app = app_counting_calls(calls, MemoryIdempotencyStore())
    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post("/v1/with-follow-up", headers={"Idempotency-Key": "k"})
        again = client.post("/v1/with-follow-up", headers={"Idempotency-Key": "k"})
    assert (first.status_code, first.json()) == (200, {"done": True})
    assert again.headers["Idempotent-Replayed"] == "true"
    assert calls == [0]


class StoreThatCannotSave(MemoryIdempotencyStore):
    async def complete(
        self, scope: str, key: str, started: datetime, response: StoredResponse
    ) -> None:
        raise ConnectionError("database went away")


def test_the_client_gets_its_answer_even_if_it_cannot_be_remembered() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, StoreThatCannotSave())) as client:
        response = client.post("/v1/orders", json={"size": 4}, headers={"Idempotency-Key": "k"})
    assert (response.status_code, response.json()) == (201, {"id": 1, "size": 4})


def test_a_run_that_lost_its_key_cannot_touch_the_new_holder() -> None:
    store = MemoryIdempotencyStore()
    now = datetime.now(UTC)
    later = now + LOCK_TIMEOUT
    answer = StoredResponse(201, [], b"late")

    async def scenario() -> None:
        await store.begin("s", "k", "f", now)
        # The first run is so slow that a repeat takes the key over.
        assert await store.begin("s", "k", "f", later) == Started()
        await store.release("s", "k", now)
        await store.complete("s", "k", now, answer)
        assert await store.begin("s", "k", "f", later) == InProgress()
        await store.complete("s", "k", later, answer)
        assert await store.begin("s", "k", "f", later) == Replay(answer)

    asyncio.run(scenario())


def test_a_cancelled_request_still_frees_its_key() -> None:
    store = MemoryIdempotencyStore()
    now = datetime.now(UTC)

    class SlowToRelease(MemoryIdempotencyStore):
        async def release(self, scope: str, key: str, started: datetime) -> None:
            await asyncio.sleep(0.05)
            await store.release(scope, key, started)

    async def scenario() -> None:
        await store.begin("s", "k", "f", now)
        task = asyncio.create_task(_Claim(SlowToRelease(), "s", "k", now).release())
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.1)
        assert ("s", "k") not in store.entries

    asyncio.run(scenario())


def test_an_answer_without_a_body_has_no_content_length() -> None:
    calls: list[int] = []
    with TestClient(app_counting_calls(calls, MemoryIdempotencyStore())) as client:
        first = client.delete("/v1/orders/7", headers={"Idempotency-Key": "k"})
        again = client.delete("/v1/orders/7", headers={"Idempotency-Key": "k"})
    assert (first.status_code, again.status_code) == (204, 204)
    assert "content-length" not in first.headers
    assert "content-length" not in again.headers
    assert calls == [7]


def test_a_cancelled_request_still_remembers_its_answer() -> None:
    store = MemoryIdempotencyStore()
    now = datetime.now(UTC)
    answer = StoredResponse(201, [], b"done")

    class SlowToSave(MemoryIdempotencyStore):
        async def complete(
            self, scope: str, key: str, started: datetime, response: StoredResponse
        ) -> None:
            await asyncio.sleep(0.05)
            await store.complete(scope, key, started, response)

    async def scenario() -> None:
        await store.begin("s", "k", "f", now)
        task = asyncio.create_task(_Claim(SlowToSave(), "s", "k", now).complete(answer))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # Shutdown waits for keys still being finished.
        await wait_for_pending_keys()
        assert await store.begin("s", "k", "f", now) == Replay(answer)

    asyncio.run(scenario())


def test_without_a_signed_in_user_the_key_is_ignored() -> None:
    calls: list[int] = []
    store = MemoryIdempotencyStore()
    app = create_app(
        readiness_checks={}, idempotency_store=store, principal_resolver=signed_in_as(None)
    )

    @app.post("/v1/things")
    def make() -> None:
        calls.append(1)

    with TestClient(app) as client:
        client.post("/v1/things", headers={"Idempotency-Key": "k"})
        again = client.post("/v1/things", headers={"Idempotency-Key": "k"})
    assert calls == [1, 1]
    assert "Idempotent-Replayed" not in again.headers
    assert store.entries == {}
