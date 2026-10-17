"""The brand kit: a workspace's stamps, fonts, colours and stamp placement (DESIGN.md 4,
10.2, T-15b).

The kit is one document, read and replaced whole. Each save names the version it was
based on, so two people editing at once cannot silently undo each other's changes.

Stamps and fonts point at the workspace's uploads. A font is named in frame specs as
``font_`` followed by its asset ID's random part (``ast_x…`` is ``font_x…``), so the
name never changes while the font is in the kit.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from framegen.api.access import AdminAccess, MemberAccess
from framegen.api.auth import Engine
from framegen.api.errors import ApiError
from framegen.db.tables import assets, brand_kits
from framegen.spec.models import Color
from framegen.spec.text import BrandText, MarkSize, Placement

router = APIRouter(tags=["brand kit"])

AssetId = Annotated[str, Field(pattern=r"^ast_[a-z2-7]{26}$")]

STAMP_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}
FONT_TYPES = {"font/ttf", "font/otf"}
"""WOFF2 fonts are not taken yet: they need unpacking first (T-72)."""

MAX_STAMP_SHAPE = 20
"""A stamp image may be at most this many times wider than tall, or taller than wide: a
thinner one would be a hairline in its slot."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrandTextStamp(Strict, BrandText):
    kind: Literal["text"]


class BrandImageStamp(Strict):
    kind: Literal["image"]
    asset: AssetId


Stamp = Annotated[BrandTextStamp | BrandImageStamp, Field(discriminator="kind")]


class BrandFont(Strict):
    asset: AssetId = Field(description="A TrueType or OpenType font upload (kind font).")
    name: str = Field(min_length=1, max_length=100, description="Shown when choosing fonts.")


class BrandFontInKit(BrandFont):
    id: str = Field(description="How frame specs name the font: font_ and the asset's ID.")


class BrandColor(Strict):
    color: Color
    name: str | None = Field(default=None, max_length=50)


class StampPlacement(Strict, MarkSize):
    """Where new frames put the stamp, and how big."""

    slot: Placement = "end-edge"
    opacity: float = Field(default=1, ge=0, le=1)


class BrandKitContent(Strict):
    stamps: list[Stamp] = Field(default_factory=list, max_length=10)
    default_stamp: int | None = Field(
        default=None, ge=0, description="The stamp frames use (its index in stamps)."
    )
    fonts: list[BrandFont] = Field(default_factory=list, max_length=20)
    colors: list[BrandColor] = Field(default_factory=list, max_length=24)
    stamp_placement: StampPlacement = Field(default_factory=StampPlacement)

    @model_validator(mode="after")
    def _default_is_a_stamp(self) -> "BrandKitContent":
        if self.default_stamp is not None and self.default_stamp >= len(self.stamps):
            raise ValueError("default_stamp is not the index of a stamp")
        return self


class BrandKitSave(BrandKitContent):
    version: int = Field(
        ge=0, description="The version this edit started from (0 if the kit was never saved)."
    )


class BrandKit(BaseModel):
    stamps: list[Stamp]
    default_stamp: int | None
    fonts: list[BrandFontInKit]
    colors: list[BrandColor]
    stamp_placement: StampPlacement
    version: int = Field(description="0 until the kit is first saved.")
    updated_at: datetime | None


def font_id(asset_id: str) -> str:
    return "font_" + asset_id.removeprefix("ast_")


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
