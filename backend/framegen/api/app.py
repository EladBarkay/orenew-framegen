import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel

from framegen import __version__
from framegen.health import Check, Readiness, default_checks
from framegen.project import LICENSE_ID, SOURCE_URL
from framegen.settings import get_settings


class Health(BaseModel):
    status: str
    version: str


class ReadinessReport(BaseModel):
    status: str
    checks: dict[str, str]


def configure_logging() -> None:
    """Show FrameGen's own INFO messages when nothing else has set up logging.

    uvicorn only configures its own loggers. Runs at application startup, not on import.
    """
    logger = logging.getLogger("framegen")
    if logger.handlers or logging.getLogger().handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def create_app(readiness_checks: Mapping[str, Check] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        # Built once at startup and reused, so bad settings stop the API from starting.
        checks = (
            readiness_checks if readiness_checks is not None else default_checks(get_settings())
        )
        app.state.readiness = Readiness(checks)
        yield

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
    )

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
