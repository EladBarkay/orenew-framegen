"""Cursor pagination for every list endpoint (DESIGN.md section 10.1).

A list answers ``{"items": [...], "next_cursor": "..." | null}``. The cursor is opaque to
clients: they pass back what they were given. Inside, it is the sort key of the last item
returned, so pages stay stable while items are added.
"""

import base64
import binascii
import json
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel

from framegen.api.errors import ApiError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Items per page.")]
Cursor = Annotated[
    str | None, Query(max_length=1024, description="The next_cursor of the previous page.")
]


def encode_cursor(position: dict[str, Any]) -> str:
    raw = json.dumps(position, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        # validate=True: characters outside the alphabet are an error, not silently skipped.
        position = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise ApiError(400, "invalid_cursor", "The cursor is not valid.") from error
    if not isinstance(position, dict):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid.")
    return position
