"""One error format for the whole API (DESIGN.md section 10.1).

Every error answers ``{"error": {"code": ..., "message": ..., "detail": ...}}``. ``code`` is
stable and meant for programs (clients translate it into their own words); ``message`` is
an English hint for developers; ``detail`` carries structured extra facts or is null.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("framegen.api")


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    """Raise anywhere in a request to answer with the shared error format."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail


def error_response(
    status: int,
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, detail=detail))
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


# Codes for errors the framework raises before our code runs.
_HTTP_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "too_many_requests",
}

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": ErrorResponse, "description": "Error"},
}
"""Add to routes (or the app) so the OpenAPI document shows the error format."""


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status, error.code, error.message, error.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            {"location": list(item.get("loc", ())), "problem": item.get("msg", "")}
            for item in error.errors()
        ]
        return error_response(
            422, "validation_failed", "The request is not valid.", {"problems": problems}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(error.status_code, "http_error")
        message = (
            error.detail if isinstance(error.detail, str) else HTTPStatus(error.status_code).phrase
        )
        # Keep the framework's headers, such as Allow on 405.
        return error_response(error.status_code, code, message, headers=error.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        log.exception("unexpected error on %s %s", request.method, request.url.path)
        return error_response(500, "internal", "Something went wrong on our side.")
