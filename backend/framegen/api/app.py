from collections.abc import Mapping

from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from framegen import __version__
from framegen.health import Check, default_checks, run_checks
from framegen.project import LICENSE_ID, SOURCE_URL
from framegen.settings import get_settings


class Health(BaseModel):
    status: str
    version: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, str]


def create_app(readiness_checks: Mapping[str, Check] | None = None) -> FastAPI:
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
    )

    @app.get("/v1/health", operation_id="getHealth", tags=["system"])
    def health() -> Health:
        """Liveness: the API process is running."""
        return Health(status="ok", version=__version__)

    @app.get(
        "/v1/health/ready",
        operation_id="getReadiness",
        tags=["system"],
        responses={503: {"model": Readiness}},
    )
    def ready(response: Response) -> Readiness:
        """Readiness: the API can reach the database and storage."""
        checks = (
            readiness_checks if readiness_checks is not None else default_checks(get_settings())
        )
        results = run_checks(checks)
        if all(result == "ok" for result in results.values()):
            return Readiness(status="ready", checks=results)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(status="unavailable", checks=results)

    return app


app = create_app()
