from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from framegen.api.app import create_app
from framegen.api.errors import ApiError
from framegen.api.idempotency import MemoryIdempotencyStore


class Thing(BaseModel):
    name: str
    size: int


def app_with_routes() -> FastAPI:
    app = create_app(readiness_checks={}, idempotency_store=MemoryIdempotencyStore())

    @app.post("/v1/things")
    def make(thing: Thing) -> Thing:
        return thing

    @app.get("/v1/things/{thing_id}")
    def get(thing_id: str) -> Thing:
        raise ApiError(404, "thing_not_found", "No such thing.", {"thing_id": thing_id})

    @app.get("/v1/odd/{status}")
    def odd(status: int) -> None:
        raise StarletteHTTPException(status)

    @app.get("/v1/broken")
    def broken() -> None:
        raise RuntimeError("bug")

    return app


def test_unknown_route_uses_the_error_format() -> None:
    with TestClient(app_with_routes()) as client:
        response = client.get("/v1/nowhere")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "detail": None}
    }


def test_wrong_method_has_a_code() -> None:
    with TestClient(app_with_routes()) as client:
        response = client.delete("/v1/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert response.headers["Allow"] == "GET"


def test_validation_errors_list_each_problem() -> None:
    with TestClient(app_with_routes()) as client:
        response = client.post("/v1/things", json={"name": "a", "size": "big"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["detail"]["problems"][0]["location"] == ["body", "size"]


def test_api_error_carries_its_code_and_detail() -> None:
    with TestClient(app_with_routes()) as client:
        response = client.get("/v1/things/42")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "thing_not_found",
            "message": "No such thing.",
            "detail": {"thing_id": "42"},
        }
    }


def test_unexpected_errors_hide_the_cause() -> None:
    with TestClient(app_with_routes(), raise_server_exceptions=False) as client:
        response = client.get("/v1/broken")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal"
    assert "bug" not in response.text


def test_openapi_documents_the_error_format() -> None:
    with TestClient(app_with_routes()) as client:
        document = client.get("/v1/openapi.json").json()
    assert "ErrorResponse" in document["components"]["schemas"]
    default = document["paths"]["/v1/health"]["get"]["responses"]["default"]
    assert default["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")


def test_unusual_statuses_are_answered_cleanly() -> None:
    with TestClient(app_with_routes()) as client:
        unnamed = client.get("/v1/odd/499")
        not_modified = client.get("/v1/odd/304")
    assert unnamed.status_code == 499
    assert unnamed.json()["error"] == {
        "code": "http_error",
        "message": "Request failed.",
        "detail": None,
    }
    assert (not_modified.status_code, not_modified.content) == (304, b"")
