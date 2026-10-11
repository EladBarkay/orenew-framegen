"""Cursor pagination for every list endpoint (DESIGN.md section 10.1).

A list answers ``{"items": [...], "next_cursor": "..." | null}``. The cursor is opaque to
clients: they pass back what they were given. Inside, it is the sort key of the last item
returned, so pages stay stable while items are added.
"""

import base64
import binascii
import json
import re
from collections.abc import Callable
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


_BASE64URL = re.compile(r"[A-Za-z0-9_-]*")
"""Checked first: the decoder silently skips other characters, and accepts + and /."""


def encode_cursor(position: dict[str, Any]) -> str:
    raw = json.dumps(position, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        if not _BASE64URL.fullmatch(cursor):
            raise ValueError("not base64url")
        position = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise ApiError(400, "invalid_cursor", "The cursor is not valid.") from error
    if not isinstance(position, dict):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid.")
    return position


def after_key(cursor: str | None) -> str:
    """For lists ordered by one text key: the key to continue after ("" for the first page)."""
    if not cursor:
        return ""
    after = decode_cursor(cursor).get("after")
    if not isinstance(after, str):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid.")
    return after


def keyset_page[T](items: list[T], limit: int, key: Callable[[T], str]) -> Page[T]:
    """A page from up to ``limit + 1`` items fetched in key order; the extra one only shows
    that another page exists."""
    page = items[:limit]
    more = len(items) > limit
    return Page(items=page, next_cursor=encode_cursor({"after": key(page[-1])}) if more else None)
