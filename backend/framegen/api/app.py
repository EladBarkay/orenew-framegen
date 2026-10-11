from fastapi import FastAPI
from pydantic import BaseModel

from framegen import __version__


class Health(BaseModel):
    status: str
    version: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="FrameGen API",
        version=__version__,
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
    )

    @app.get("/v1/health", operation_id="getHealth", tags=["system"])
    def health() -> Health:
        return Health(status="ok", version=__version__)

    return app


app = create_app()
