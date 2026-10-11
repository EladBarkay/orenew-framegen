import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel

from framegen import __version__
from framegen.api import auth, workspaces
from framegen.api.errors import ERROR_RESPONSES, install_error_handlers
from framegen.api.idempotency import (
    IdempotencyMiddleware,
    IdempotencyStore,
    PrincipalResolver,
    wait_for_pending_keys,
)
from framegen.db.engine import async_engine
from framegen.db.idempotency_store import PostgresIdempotencyStore
from framegen.health import Check, Readiness, default_checks
from framegen.project import LICENSE_ID, SOURCE_URL
from framegen.settings import Settings, get_settings


class Health(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessReport(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: dict[str, Literal["ok", "unavailable"]]


def configure_logging() -> None:
    """Show FrameGen's own INFO messages. Runs at application startup, not on import.

    uvicorn only configures its own loggers. If the host configured logging (a root
    handler), FrameGen's messages go there; otherwise FrameGen prints them itself, and does
    not also pass them on, so nothing is printed twice.
    """
    logger = logging.getLogger("framegen")
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if logger.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False


def create_app(
    readiness_checks: Mapping[str, Check] | None = None,
    idempotency_store: IdempotencyStore | None = None,
    settings: Settings | None = None,
    principal_resolver: PrincipalResolver | None = None,
) -> FastAPI:
    """The API. Tests may pass their own settings, checks, idempotency store and principal
    resolver; otherwise they come from the environment and the database."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app_settings = settings or get_settings()
        app.state.settings = app_settings
        # Built once at startup and reused, so bad settings stop the API from starting.
        checks = readiness_checks if readiness_checks is not None else default_checks(app_settings)
        app.state.readiness = Readiness(checks)
        # Connects lazily: nothing is opened until a request needs the database.
        engine = async_engine(app_settings)
        app.state.engine = engine
        app.state.idempotency_store = idempotency_store or PostgresIdempotencyStore(engine)
        app.state.principal_resolver = principal_resolver or auth.principal_from_session
        try:
            yield
        finally:
            await wait_for_pending_keys()
            await engine.dispose()

    app = FastAPI(
        title="FrameGen API",
        version=__version__,
        description=(
            "FrameGen is free software under the GNU Affero General Public License, "
            f"version 3 only. Source code: {SOURCE_URL}"
        ),
        license_info={
            "name": "GNU Affero General Public License v3.0 only",
            "identifier": LICENSE_ID,
        },
        contact={"name": "Orenew FrameGen", "url": SOURCE_URL},
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    install_error_handlers(app)
    app.add_middleware(IdempotencyMiddleware)
    app.include_router(auth.router)
    app.include_router(workspaces.router)

    @app.get("/v1/health", operation_id="getHealth", tags=["system"])
    def health() -> Health:
        """Liveness: the API process is running."""
        return Health(status="ok", version=__version__)

    # Outside /v1: the public entrance (Caddy) forwards only /v1, so this stays inside the
    # deployment, and it is not part of the public API or its documentation.
    @app.get("/internal/health/ready", include_in_schema=False)
    async def ready(request: Request, response: Response) -> ReadinessReport:
        """Readiness: the API can reach the database and storage."""
        readiness: Readiness = request.app.state.readiness
        results = await readiness.run()
        if all(result == "ok" for result in results.values()):
            return ReadinessReport(status="ready", checks=results)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessReport(status="unavailable", checks=results)

    return app


app = create_app()
