"""Idempotency-Key support for every mutating request (DESIGN.md section 10.1).

A client that sends ``Idempotency-Key: <key>`` with a POST, PUT, PATCH or DELETE can safely
retry it: the first request runs, and a repeat with the same key and the same request gets
the first response back (marked ``Idempotent-Replayed: true``) without running again.

- The same key with a different request is refused (422 ``idempotency_key_reused``).
- A repeat that arrives while the first is still running is refused
  (409 ``idempotency_key_in_progress``); the client retries a little later.
- Server errors (5xx) are not remembered, so the client can retry them.
- Keys are remembered for 24 hours.
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from framegen.api.errors import error_response

log = logging.getLogger("framegen.api")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
KEY_HEADER = b"idempotency-key"
REPLAYED_HEADER = (b"idempotent-replayed", b"true")
KEPT_FOR = timedelta(hours=24)
LOCK_TIMEOUT = timedelta(minutes=2)
"""A first request still unfinished after this is taken to have crashed; a repeat may run."""
MAX_BODY_BYTES = 10 * 1024 * 1024
"""Large files never pass through the API (pre-signed uploads), so bodies are small."""


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    headers: list[tuple[str, str]]
    body: bytes


@dataclass(frozen=True)
class Started:
    """This request is the first with its key: run it."""


@dataclass(frozen=True)
class Replay:
    response: StoredResponse


@dataclass(frozen=True)
class InProgress:
    pass


@dataclass(frozen=True)
class Mismatch:
    pass


BeginResult = Started | Replay | InProgress | Mismatch


class IdempotencyStore(Protocol):
    async def begin(self, scope: str, key: str, fingerprint: str, now: datetime) -> BeginResult: ...

    async def complete(self, scope: str, key: str, response: StoredResponse) -> None: ...

    async def release(self, scope: str, key: str) -> None: ...


@dataclass
class _Entry:
    fingerprint: str
    started_at: datetime
    expires_at: datetime
    response: StoredResponse | None = None


@dataclass
class MemoryIdempotencyStore:
    """For tests and single-process development. Production uses the Postgres store."""

    entries: dict[tuple[str, str], _Entry] = field(default_factory=dict)

    async def begin(self, scope: str, key: str, fingerprint: str, now: datetime) -> BeginResult:
        entry = self.entries.get((scope, key))
        if entry is None or entry.expires_at <= now:
            self.entries[(scope, key)] = _Entry(fingerprint, now, now + KEPT_FOR)
            return Started()
        if entry.fingerprint != fingerprint:
            return Mismatch()
        if entry.response is not None:
            return Replay(entry.response)
        if entry.started_at <= now - LOCK_TIMEOUT:
            entry.started_at = now
            return Started()
        return InProgress()

    async def complete(self, scope: str, key: str, response: StoredResponse) -> None:
        self.entries[(scope, key)].response = response

    async def release(self, scope: str, key: str) -> None:
        self.entries.pop((scope, key), None)


def _valid_key(raw: bytes) -> str | None:
    try:
        key = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not 1 <= len(key) <= 255 or not key.isprintable():
        return None
    return key


def fingerprint(method: str, path: str, query: bytes, body: bytes) -> str:
    digest = hashlib.sha256()
    for part in (method.encode(), path.encode(), query, body):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


class IdempotencyMiddleware:
    """ASGI middleware; the store comes from ``app.state.idempotency_store`` (set at startup)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        raw_key = dict(scope["headers"]).get(KEY_HEADER)
        if raw_key is None:
            await self.app(scope, receive, send)
            return

        async def answer(status: int, code: str, message: str) -> None:
            await error_response(status, code, message)(scope, receive, send)

        key = _valid_key(raw_key)
        if key is None:
            await answer(
                400, "invalid_idempotency_key", "Idempotency-Key must be 1-255 ASCII characters."
            )
            return
        store: IdempotencyStore | None = getattr(scope["app"].state, "idempotency_store", None)
        if store is None:
            await answer(503, "idempotency_unavailable", "Idempotency-Key cannot be honoured now.")
            return

        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY_BYTES:
                await answer(413, "payload_too_large", "The request body is too large.")
                return

        owner = "anonymous"  # who sent it; accounts arrive in T-06
        method, path = scope["method"], scope["path"]
        result = await store.begin(
            owner, key, fingerprint(method, path, scope["query_string"], body), datetime.now(UTC)
        )
        if isinstance(result, Mismatch):
            await answer(
                422, "idempotency_key_reused", "This Idempotency-Key was used for another request."
            )
            return
        if isinstance(result, InProgress):
            await answer(
                409,
                "idempotency_key_in_progress",
                "A request with this Idempotency-Key is still being handled; retry shortly.",
            )
            return
        if isinstance(result, Replay):
            await _send_stored(result.response, send)
            return

        await self._run_first(scope, body, send, store, owner, key)

    async def _run_first(
        self, scope: Scope, body: bytes, send: Send, store: IdempotencyStore, owner: str, key: str
    ) -> None:
        delivered = False

        async def replay_body() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        status = 500
        headers: list[tuple[bytes, bytes]] = []
        chunks: list[bytes] = []

        async def capture(message: Message) -> None:
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        try:
            await self.app(scope, replay_body, capture)
        except BaseException:
            await store.release(owner, key)
            raise

        stored = StoredResponse(
            status_code=status,
            headers=[
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in headers
                if name.lower() not in (b"content-length", b"set-cookie")
            ],
            body=b"".join(chunks),
        )
        if status >= 500:
            await store.release(owner, key)
        else:
            await store.complete(owner, key, stored)
        await _send_stored(stored, send, replayed=False)


async def _send_stored(response: StoredResponse, send: Send, replayed: bool = True) -> None:
    headers = [
        (name.encode("latin-1"), value.encode("latin-1")) for name, value in response.headers
    ]
    headers.append((b"content-length", str(len(response.body)).encode()))
    if replayed:
        headers.append(REPLAYED_HEADER)
    await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": response.body})
