"""The brand kit's content (DESIGN.md 4, T-15b), and what the renderer needs from it for
one frame spec: the kit's stamp, if the spec uses it, and the files of the workspace fonts
the spec names. The API (framegen.api.brand_kit) stores and checks it.

Stamps and fonts point at the workspace's uploads. A font is named in frame specs as
``font_`` followed by its asset ID's random part (``ast_x…`` is ``font_x…``), so the
name never changes while the font is in the kit.

Files are read through `read`, given an asset's storage key, so this works with any
storage (the worker passes its S3 client's reader).
"""

import asyncio
import base64
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from framegen.db.tables import assets, brand_kits
from framegen.render.svg import Image
from framegen.render.text import FontFile
from framegen.spec import FrameSpec
from framegen.spec.models import AssetRef, Color, Fraction
from framegen.spec.text import (
    MAX_TEXT_SIZE,
    BrandKitStamp,
    BrandText,
    MarkSize,
    Placement,
    TextStamp,
)

STAMP_TYPES = {"image/png", "image/jpeg", "image/svg+xml"}
FONT_TYPES = {"font/ttf", "font/otf"}
"""WOFF2 fonts are not taken yet: they need unpacking first (T-72)."""

MAX_VERSION = 2**31 - 2
"""So the next version still fits the database's integer."""

MAX_STAMP_SHAPE = 20
"""A stamp image may be at most this many times wider than tall, or taller than wide: a
thinner one would be a hairline in its slot."""


class Strict(BaseModel):
    # As the spec's models: no unknown fields, and no coercion ("1" or true for 1).
    model_config = ConfigDict(extra="forbid", strict=True)


class BrandTextStamp(Strict, BrandText):
    kind: Literal["text"]


class BrandImageStamp(Strict):
    kind: Literal["image"]
    asset: AssetRef


Stamp = Annotated[BrandTextStamp | BrandImageStamp, Field(discriminator="kind")]


class BrandFont(Strict):
    asset: AssetRef = Field(description="A TrueType or OpenType font upload (kind font).")
    name: str = Field(min_length=1, max_length=100, description="Shown when choosing fonts.")


class BrandFontInKit(BrandFont):
    id: str = Field(description="How frame specs name the font: font_ and the asset's ID.")


class BrandColor(Strict):
    color: Color
    name: str | None = Field(default=None, max_length=50)


class StampPlacement(Strict, MarkSize):
    """Where new frames put the stamp, and how big."""

    slot: Placement = "end-edge"
    opacity: Fraction = 1


class BrandKitContent(Strict):
    stamps: list[Stamp] = Field(default_factory=list, max_length=10)
    default_stamp: int | None = Field(
        default=None, ge=0, description="The stamp frames use (its index in stamps)."
    )
    fonts: list[BrandFont] = Field(default_factory=list, max_length=20)
    colors: list[BrandColor] = Field(default_factory=list, max_length=24)
    stamp_placement: StampPlacement = Field(default_factory=StampPlacement)

    @model_validator(mode="after")
    def _consistent(self) -> "BrandKitContent":
        if self.default_stamp is not None:
            if self.default_stamp >= len(self.stamps):
                raise ValueError("default_stamp is not the index of a stamp")
            text = isinstance(self.stamps[self.default_stamp], BrandTextStamp)
            if text and self.stamp_placement.size > MAX_TEXT_SIZE:
                raise ValueError(
                    f"for a text stamp the size is a text height: at most {MAX_TEXT_SIZE}"
                )
        if len({font.asset for font in self.fonts}) < len(self.fonts):
            raise ValueError("a font is in the kit twice")
        return self


class BrandKitSave(BrandKitContent):
    version: int = Field(
        ge=0,
        le=MAX_VERSION,
        description="The version this edit started from (0 if the kit was never saved).",
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


Read = Callable[[str], Awaitable[bytes]]


class NoBrandStamp(ValueError):
    """The spec uses the brand kit's stamp, and the kit has none."""


class FontNotInKit(ValueError):
    """The spec names a workspace font the kit no longer has."""


async def brand_inputs(
    conn: AsyncConnection, workspace_id: str, spec: FrameSpec, read: Read
) -> tuple[BrandText | Image | None, dict[str, FontFile]]:
    """The brand kit's stamp (None if the spec does not use it) and the workspace fonts the
    spec and that stamp name, by their font_ IDs."""
    saved = (
        await conn.execute(
            select(brand_kits.c.content).where(brand_kits.c.workspace_id == workspace_id)
        )
    ).first()
    kit = BrandKitContent.model_validate(saved.content) if saved else BrandKitContent()
    stamp: BrandText | Image | None = None
    if isinstance(spec.stamp, BrandKitStamp):
        if kit.default_stamp is None:
            raise NoBrandStamp("the frame uses the brand kit's stamp; the kit has none")
        chosen = kit.stamps[kit.default_stamp]
        if isinstance(chosen, BrandImageStamp):
            row = (await _assets(conn, workspace_id, [chosen.asset]))[chosen.asset]
            data = base64.b64encode(await read(row["storage_key"])).decode("ascii")
            stamp = Image(f"data:{row['content_type']};base64,{data}", row["width"], row["height"])
        else:
            stamp = BrandText(text=chosen.text, font=chosen.font, color=chosen.color)
    named = {part.font for part in (spec.headline, spec.date) if part is not None}
    for text in (spec.stamp, stamp):
        if isinstance(text, TextStamp | BrandText):
            named.add(text.font)
    in_kit = {font_id(font.asset): font.asset for font in kit.fonts}
    wanted = sorted(ref for ref in named if ref.startswith("font_"))
    if missing := [ref for ref in wanted if ref not in in_kit]:
        raise FontNotInKit(f"the frame names {', '.join(missing)}, not in the brand kit")
    rows = await _assets(conn, workspace_id, [in_kit[ref] for ref in wanted])
    files = await asyncio.gather(*(read(rows[in_kit[ref]]["storage_key"]) for ref in wanted))
    return stamp, {ref: FontFile(data) for ref, data in zip(wanted, files, strict=True)}


async def _assets(
    conn: AsyncConnection, workspace_id: str, ids: list[str]
) -> dict[str, dict[str, Any]]:
    """The workspace's ready uploads with these IDs, in one query; all must be there."""
    if not ids:
        return {}
    rows = (
        await conn.execute(
            select(assets).where(
                assets.c.workspace_id == workspace_id,
                assets.c.id.in_(ids),
                assets.c.status == "ready",
            )
        )
    ).mappings()
    found = {row["id"]: dict(row) for row in rows}
    if missing := set(ids) - found.keys():
        raise LookupError(f"the brand kit names {', '.join(sorted(missing))}: not ready uploads")
    return found
