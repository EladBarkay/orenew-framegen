"""File uploads (DESIGN.md section 6.2, T-07).

Files go straight from the client to storage; the API never carries them.

1. ``createAsset`` with the file's name, type, size and sha256. The answer has a
   pre-signed ``PUT`` link and the headers to send with it. The link is signed with the
   size and sha256, so storage itself refuses any other content.
2. The client uploads the file to that link.
3. ``completeAsset``. FrameGen checks that the file arrived and that its first bytes
   really are the declared type, and reads its pixel size. The asset is then ``ready``.

Downloads use short-lived pre-signed links that always download (never open in the
browser), so even an SVG cannot run in the site's name.
"""

from __future__ import annotations

import asyncio
import base64
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi import APIRouter, Path, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from framegen.api.access import MemberAccess
from framegen.api.auth import AppSettings, Engine
from framegen.api.errors import ApiError
from framegen.api.pagination import DEFAULT_LIMIT, Cursor, Limit, Page, after_key, keyset_page
from framegen.assets.filetypes import HEADER_BYTES, TYPES, pixel_size
from framegen.db.tables import assets
from framegen.ids import new_id
from framegen.storage.client import MISSING, error_code

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

UPLOAD_LINK_LIFETIME = timedelta(hours=1)
DOWNLOAD_LINK_LIFETIME = timedelta(minutes=15)

UploadKind = Literal["reference", "font", "stamp", "template-source"]
AssetKind = Literal["reference", "font", "stamp", "template-source", "piece", "render", "package"]
ContentType = Literal[
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/tiff",
    "image/vnd.adobe.photoshop",
    "application/pdf",
    "image/svg+xml",
    "font/ttf",
    "font/otf",
    "font/woff2",
]
assert set(ContentType.__args__) == set(TYPES)  # type: ignore[attr-defined]

router = APIRouter(tags=["assets"])

_UNSAFE_IN_FILENAME = re.compile(r'[\x00-\x1f\x7f/\\"]')


class AssetCreate(BaseModel):
    kind: UploadKind
    filename: str = Field(min_length=1, max_length=255, description="The file's name.")
    content_type: ContentType
    size: int = Field(gt=0, description="In bytes.")
    sha256: str = Field(pattern="^[0-9a-f]{64}$", description="The content's SHA-256, hex.")

    @field_validator("filename")
    @classmethod
    def plain_name(cls, value: str) -> str:
        name = _UNSAFE_IN_FILENAME.sub("_", value).strip()
        if not name or name in {".", ".."}:
            raise ValueError("not a file name")
        return name


class Asset(BaseModel):
    id: str
    kind: AssetKind
    status: Literal["pending", "ready"]
    filename: str
    content_type: ContentType
    size: int
    sha256: str
    width: int | None = Field(description="Pixel width, when the file has one.")
    height: int | None
    created_at: datetime
    download_url: str | None = Field(
        description="A link that downloads the file, valid for 15 minutes (ready assets)."
    )


class Upload(BaseModel):
    url: str
    method: Literal["PUT"]
    headers: dict[str, str] = Field(description="Send exactly these headers with the upload.")
    expires_at: datetime


class CreatedAsset(BaseModel):
    asset: Asset
    upload: Upload


AssetId = Annotated[str, Path(max_length=40, description="The asset's ID.")]
Row = Mapping[str, Any]


def _clients(request: Request) -> tuple[S3Client, S3Client]:
    return request.app.state.storage, request.app.state.presigner


def _hex_to_base64(sha256: str) -> str:
    return base64.b64encode(bytes.fromhex(sha256)).decode()


def _download_url(presigner: S3Client, bucket: str, row: Row) -> str:
    # An ASCII name for old clients, and the real one (RFC 6266) for everything else.
    plain = row["filename"].encode("ascii", "replace").decode().replace("?", "_")
    disposition = f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(row['filename'])}"
    return presigner.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": row["storage_key"],
            "ResponseContentType": row["content_type"],
            "ResponseContentDisposition": disposition,
        },
        ExpiresIn=int(DOWNLOAD_LINK_LIFETIME.total_seconds()),
    )


def _asset(row: Row, presigner: S3Client | None = None, bucket: str = "") -> Asset:
    ready = row["status"] == "ready"
    return Asset(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        filename=row["filename"],
        content_type=row["content_type"],
        size=row["size"],
        sha256=row["sha256"],
        width=row["width"],
        height=row["height"],
        created_at=row["created_at"],
        download_url=_download_url(presigner, bucket, row) if ready and presigner else None,
    )


@router.post(
    "/v1/workspaces/{workspace_id}/assets",
    operation_id="createAsset",
    status_code=status.HTTP_201_CREATED,
)
async def create_asset(
    body: AssetCreate, access: MemberAccess, engine: Engine, settings: AppSettings, request: Request
) -> CreatedAsset:
    """Start an upload: returns the asset (pending) and where to upload the file."""
    file_type = TYPES[body.content_type]
    if (file_type.family == "font") != (body.kind == "font"):
        raise ApiError(
            422,
            "kind_does_not_match_type",
            "Fonts are uploaded as kind font, and only fonts are.",
        )
    if not body.filename.lower().endswith(file_type.extensions):
        raise ApiError(
            422,
            "extension_does_not_match_type",
            "The file name's extension does not match its type.",
            {"expected": list(file_type.extensions)},
        )
    if body.size > file_type.max_size:
        raise ApiError(
            413,
            "file_too_large",
            "The file is larger than allowed for its type.",
            {"max_size": file_type.max_size},
        )
    asset_id = new_id("ast")
    now = datetime.now(UTC)
    row = {
        "id": asset_id,
        "workspace_id": access.workspace_id,
        "kind": body.kind,
        "status": "pending",
        "storage_key": f"workspaces/{access.workspace_id}/assets/{asset_id}",
        "filename": body.filename,
        "content_type": body.content_type,
        "size": body.size,
        "sha256": body.sha256,
        "width": None,
        "height": None,
        "created_by": access.user.id,
        "created_at": now,
    }
    async with engine.begin() as conn:
        await conn.execute(insert(assets).values(**row))
    _, presigner = _clients(request)
    checksum = _hex_to_base64(body.sha256)
    url = presigner.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": row["storage_key"],
            "ContentType": body.content_type,
            # Both signed, so storage refuses any other size or content.
            "ContentLength": body.size,
            "ChecksumSHA256": checksum,
        },
        ExpiresIn=int(UPLOAD_LINK_LIFETIME.total_seconds()),
    )
    return CreatedAsset(
        asset=_asset(row),
        upload=Upload(
            url=url,
            method="PUT",
            headers={"Content-Type": body.content_type, "x-amz-checksum-sha256": checksum},
            expires_at=now + UPLOAD_LINK_LIFETIME,
        ),
    )


@router.post(
    "/v1/workspaces/{workspace_id}/assets/{asset_id}/complete", operation_id="completeAsset"
)
async def complete_asset(
    asset_id: AssetId,
    access: MemberAccess,
    engine: Engine,
    settings: AppSettings,
    request: Request,
) -> Asset:
    """Confirm an upload. Safe to repeat: a ready asset is simply returned."""
    row = await _find(engine, access.workspace_id, asset_id)
    storage, presigner = _clients(request)
    if row["status"] == "ready":
        return _asset(row, presigner, settings.s3_bucket)
    bucket, key = settings.s3_bucket, row["storage_key"]

    def inspect() -> tuple[dict[str, Any] | None, bytes]:
        try:
            head = storage.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        except ClientError as error:
            if error_code(error) in MISSING:
                return None, b""
            raise
        return dict(head), _read(storage, bucket, key, 0, HEADER_BYTES)

    head, first_bytes = await asyncio.to_thread(inspect)
    if head is None:
        raise ApiError(409, "upload_missing", "The file has not been uploaded yet.")

    async def reject(status_code: int, code: str, message: str) -> ApiError:
        """Delete the stored file, so it can never be served, and mark the asset rejected.
        The row stays, so retention also removes anything uploaded again later through the
        still-valid link."""
        async with engine.begin() as conn:
            await conn.execute(
                update(assets).where(assets.c.id == asset_id).values(status="rejected")
            )
        await asyncio.to_thread(storage.delete_object, Bucket=bucket, Key=key)
        return ApiError(status_code, code, message)

    if head.get("ContentLength") != row["size"] or head.get("ChecksumSHA256") != _hex_to_base64(
        row["sha256"]
    ):
        # Storage checks the signed size and checksum, so this only happens if bypassed.
        raise await reject(409, "upload_mismatch", "The uploaded file is not the one declared.")
    if not TYPES[row["content_type"]].matches(first_bytes):
        raise await reject(
            422, "not_the_declared_type", "The file's content does not match its declared type."
        )

    def read(offset: int, length: int) -> bytes:
        # A file shorter than HEADER_BYTES is already here whole.
        if offset + length <= len(first_bytes) or len(first_bytes) < HEADER_BYTES:
            return first_bytes[offset : offset + length]
        return _read(storage, bucket, key, offset, length)

    size = await asyncio.to_thread(pixel_size, row["content_type"], read)
    async with engine.begin() as conn:
        result = await conn.execute(
            update(assets)
            .where(assets.c.id == asset_id, assets.c.status == "pending")
            .values(
                status="ready",
                width=size[0] if size else None,
                height=size[1] if size else None,
                completed_at=datetime.now(UTC),
            )
            .returning(*assets.c)
        )
        updated = result.mappings().first()
    if updated is not None:
        return _asset(dict(updated), presigner, bucket)
    return _asset(await _find(engine, access.workspace_id, asset_id), presigner, bucket)


@router.get("/v1/workspaces/{workspace_id}/assets/{asset_id}", operation_id="getAsset")
async def get_asset(
    asset_id: AssetId, access: MemberAccess, engine: Engine, settings: AppSettings, request: Request
) -> Asset:
    row = await _find(engine, access.workspace_id, asset_id)
    return _asset(row, _clients(request)[1], settings.s3_bucket)


@router.get("/v1/workspaces/{workspace_id}/assets", operation_id="listAssets")
async def list_assets(
    access: MemberAccess,
    engine: Engine,
    settings: AppSettings,
    request: Request,
    kind: Annotated[AssetKind | None, Query(description="Only assets of this kind.")] = None,
    limit: Limit = DEFAULT_LIMIT,
    cursor: Cursor = None,
) -> Page[Asset]:
    """Ready assets of the workspace, oldest first."""
    query = (
        select(assets)
        .where(assets.c.workspace_id == access.workspace_id, assets.c.status == "ready")
        .where(assets.c.id > after_key(cursor))
        .order_by(assets.c.id)
        .limit(limit + 1)
    )
    if kind is not None:
        query = query.where(assets.c.kind == kind)
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).mappings().all()
    presigner = _clients(request)[1]
    items = [_asset(dict(row), presigner, settings.s3_bucket) for row in rows]
    return keyset_page(items, limit, lambda a: a.id)


async def _find(engine: AsyncEngine, workspace_id: str, asset_id: str) -> Row:
    query = select(assets).where(
        assets.c.workspace_id == workspace_id,
        assets.c.id == asset_id,
        assets.c.status != "rejected",
    )
    async with engine.connect() as conn:
        row = (await conn.execute(query)).mappings().first()
    if row is None:
        raise ApiError(404, "asset_not_found", "No such asset.")
    return dict(row)


def _read(storage: S3Client, bucket: str, key: str, offset: int, length: int) -> bytes:
    try:
        answer = storage.get_object(
            Bucket=bucket, Key=key, Range=f"bytes={offset}-{offset + length - 1}"
        )
    except ClientError as error:
        if error_code(error) == "InvalidRange":
            return b""  # past the end of the file
        raise
    data: bytes = answer["Body"].read()
    return data
