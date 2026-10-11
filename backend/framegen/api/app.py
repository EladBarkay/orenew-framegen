from fastapi import FastAPI
from pydantic import BaseModel

from framegen import __version__
from framegen.project import LICENSE_ID, SOURCE_URL


class Health(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
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
        return Health(status="ok", version=__version__)

    return app


app = create_app()
