import logging
import threading
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
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
    built: list[Readiness] = []
    lock = threading.Lock()

    def readiness() -> Readiness:
        # Built once, on first use: the checks and their storage client are reused.
        with lock:
            if not built:
                checks = readiness_checks
                if checks is None:
                    checks = default_checks(get_settings())
                built.append(Readiness(checks))
            return built[0]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
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

    @app.get(
        "/v1/health/ready",
        operation_id="getReadiness",
        tags=["system"],
        responses={503: {"model": ReadinessReport}},
    )
    async def ready(response: Response) -> ReadinessReport:
        """Readiness: the API can reach the database and storage."""
        results = await readiness().run()
        if all(result == "ok" for result in results.values()):
            return ReadinessReport(status="ready", checks=results)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessReport(status="unavailable", checks=results)

    return app


app = create_app()
