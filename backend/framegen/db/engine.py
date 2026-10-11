from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from framegen.settings import Settings

_CONNECT_ARGS = {"connect_timeout": 5}


def async_engine(settings: Settings) -> AsyncEngine:
    """For the API. One per process; it holds the connection pool."""
    return create_async_engine(
        settings.database_url, pool_pre_ping=True, connect_args=_CONNECT_ARGS
    )


def sync_engine(settings: Settings) -> Engine:
    """For commands and migrations."""
    return create_engine(settings.database_url, pool_pre_ping=True, connect_args=_CONNECT_ARGS)
