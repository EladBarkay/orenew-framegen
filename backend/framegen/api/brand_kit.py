"""The brand kit's API: a workspace's stamps, fonts, colours and stamp placement
(DESIGN.md 4, 10.2, T-15b). The kit's content is framegen.brand's.

The kit is one document, read and replaced whole. Each save names the version it was
based on, so two people editing at once cannot silently undo each other's changes.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from framegen.api.access import AdminAccess, MemberAccess
from framegen.api.auth import Engine
from framegen.api.errors import ApiError
from framegen.brand import (
    FONT_TYPES,
    MAX_STAMP_SHAPE,
    STAMP_TYPES,
    BrandFontInKit,
    BrandImageStamp,
    BrandKit,
    BrandKitContent,
    BrandKitSave,
    BrandTextStamp,
    font_id,
)
from framegen.db.tables import assets, brand_kits

router = APIRouter(tags=["brand kit"])


def _kit(content: BrandKitContent, version: int, updated_at: datetime | None) -> BrandKit:
    return BrandKit(
        stamps=content.stamps,
        default_stamp=content.default_stamp,
        fonts=[BrandFontInKit(id=font_id(f.asset), **f.model_dump()) for f in content.fonts],
        colors=content.colors,
        stamp_placement=content.stamp_placement,
        version=version,
        updated_at=updated_at,
    )


@router.get("/v1/workspaces/{workspace_id}/brand-kit", operation_id="getBrandKit")
async def get_brand_kit(access: MemberAccess, engine: Engine) -> BrandKit:
    """The workspace's brand kit; empty (version 0) until first saved."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(brand_kits).where(brand_kits.c.workspace_id == access.workspace_id)
            )
        ).first()
    if row is None:
        return _kit(BrandKitContent(), 0, None)
    return _kit(BrandKitContent.model_validate(row.content), row.version, row.updated_at)


@router.put("/v1/workspaces/{workspace_id}/brand-kit", operation_id="saveBrandKit")
async def save_brand_kit(body: BrandKitSave, access: AdminAccess, engine: Engine) -> BrandKit:
    """Replace the brand kit (admins). Refused with 409 brand_kit_changed if it was saved
    since `version`: read it again and redo the edit."""
    content = BrandKitContent.model_validate(body.model_dump(exclude={"version"}))
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await _check_references(conn, access.workspace_id, content)
        stored = content.model_dump(mode="json")
        values = {"content": stored, "updated_by": access.user.id, "updated_at": now}
        if body.version == 0:
            # A first save: refused if someone else saved first.
            saved = await conn.execute(
                pg_insert(brand_kits)
                .values(workspace_id=access.workspace_id, version=1, **values)
                .on_conflict_do_nothing(index_elements=[brand_kits.c.workspace_id])
                .returning(brand_kits.c.version)
            )
        else:
            saved = await conn.execute(
                update(brand_kits)
                .where(
                    brand_kits.c.workspace_id == access.workspace_id,
                    brand_kits.c.version == body.version,
                )
                .values(version=body.version + 1, **values)
                .returning(brand_kits.c.version)
            )
        if saved.first() is None:
            raise ApiError(
                409,
                "brand_kit_changed",
                "The brand kit was saved since this version. Read it again and redo the edit.",
            )
    return _kit(content, body.version + 1, now)


async def _check_references(
    conn: AsyncConnection, workspace_id: str, content: BrandKitContent
) -> None:
    """Every upload the kit names is the workspace's, ready, and of the right type; text
    stamps use built-in fonts or the kit's own."""
    wanted = {f.asset for f in content.fonts} | {
        s.asset for s in content.stamps if isinstance(s, BrandImageStamp)
    }
    rows = (
        await conn.execute(
            select(assets).where(
                assets.c.workspace_id == workspace_id,
                assets.c.id.in_(wanted),
                assets.c.status == "ready",
            )
        )
    ).mappings()
    found = {row["id"]: row for row in rows}

    def problem(code: str, message: str, where: str) -> ApiError:
        return ApiError(422, code, message, {"field": where})

    for i, font in enumerate(content.fonts):
        row = found.get(font.asset)
        if row is None or row["kind"] != "font":
            raise problem("font_not_found", "No such font upload.", f"fonts[{i}].asset")
        if row["content_type"] not in FONT_TYPES:
            raise problem(
                "font_format_unsupported",
                "Fonts must be TrueType or OpenType for now.",
                f"fonts[{i}].asset",
            )
    kit_fonts = {font_id(f.asset) for f in content.fonts}
    for i, stamp in enumerate(content.stamps):
        if isinstance(stamp, BrandTextStamp):
            if stamp.font.startswith("font_") and stamp.font not in kit_fonts:
                raise problem(
                    "font_not_in_kit",
                    "A text stamp's font must be built in or one of the kit's fonts.",
                    f"stamps[{i}].font",
                )
            continue
        row = found.get(stamp.asset)
        if row is None or row["kind"] != "stamp":
            raise problem("stamp_not_found", "No such stamp upload.", f"stamps[{i}].asset")
        if row["content_type"] not in STAMP_TYPES:
            raise problem(
                "stamp_format_unsupported",
                "Stamp images must be PNG, JPEG or SVG.",
                f"stamps[{i}].asset",
            )
        width, height = row["width"], row["height"]
        if not width or not height:
            raise problem(
                "stamp_size_unknown",
                "The stamp image's size could not be read.",
                f"stamps[{i}].asset",
            )
        if max(width, height) > MAX_STAMP_SHAPE * min(width, height):
            raise problem(
                "stamp_too_thin",
                f"A stamp image may be at most {MAX_STAMP_SHAPE} times wider than tall.",
                f"stamps[{i}].asset",
            )
