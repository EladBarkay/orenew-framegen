from fastapi import FastAPI
from fastapi.testclient import TestClient

from framegen.api.app import create_app
from framegen.api.idempotency import MemoryIdempotencyStore
from framegen.api.pagination import (
    DEFAULT_LIMIT,
    Cursor,
    Limit,
    Page,
    decode_cursor,
    encode_cursor,
)

NAMES = [f"item-{n:02d}" for n in range(7)]


def app_with_list() -> FastAPI:
    app = create_app(readiness_checks={}, idempotency_store=MemoryIdempotencyStore())

    @app.get("/v1/items")
    def items(limit: Limit = DEFAULT_LIMIT, cursor: Cursor = None) -> Page[str]:
        after = decode_cursor(cursor)["after"] if cursor else ""
        rest = [name for name in NAMES if name > after]
        page = rest[:limit]
        more = len(rest) > limit
        return Page(items=page, next_cursor=encode_cursor({"after": page[-1]}) if more else None)

    return app


def test_cursor_round_trips() -> None:
    assert decode_cursor(encode_cursor({"after": "x", "n": 3})) == {"after": "x", "n": 3}


def test_walking_the_pages_returns_every_item_once() -> None:
    seen: list[str] = []
    cursor = None
    with TestClient(app_with_list()) as client:
        while True:
            params: dict[str, str | int] = {"limit": 3}
            if cursor:
                params["cursor"] = cursor
            page = client.get("/v1/items", params=params).json()
            seen += page["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
    assert seen == NAMES


def test_a_broken_cursor_is_a_clear_error() -> None:
    with TestClient(app_with_list()) as client:
        response = client.get("/v1/items", params={"cursor": "%%%not-base64"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_limit_is_bounded() -> None:
    with TestClient(app_with_list()) as client:
        assert client.get("/v1/items", params={"limit": 101}).status_code == 422
        assert client.get("/v1/items", params={"limit": 0}).status_code == 422
