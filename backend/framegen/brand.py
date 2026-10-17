"""What the renderer needs from a workspace's brand kit for one frame spec (T-15b): the
kit's stamp, if the spec uses it, and the files of the workspace fonts the spec names.

Files are read through `read`, given an asset's storage key, so this works with any
storage (the worker passes its S3 client's reader).
"""

import base64
from collections.abc import Awaitable, Callable

from sqlalchemy import RowMapping, select
from sqlalchemy.ext.asyncio import AsyncConnection

from framegen.api.brand_kit import BrandImageStamp, BrandKitContent, font_id
from framegen.db.tables import assets, brand_kits
from framegen.render.svg import Image
from framegen.render.text import FontFile
from framegen.spec import FrameSpec
from framegen.spec.text import BrandKitStamp, BrandText, TextStamp

Read = Callable[[str], Awaitable[bytes]]


class NoBrandStamp(ValueError):
    """The spec uses the brand kit's stamp, and the kit has none."""


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
            row = await _asset(conn, workspace_id, chosen.asset)
            data = base64.b64encode(await read(row["storage_key"])).decode("ascii")
            stamp = Image(f"data:{row['content_type']};base64,{data}", row["width"], row["height"])
        else:
            stamp = BrandText(text=chosen.text, font=chosen.font, color=chosen.color)
    named = {part.font for part in (spec.headline, spec.date) if part is not None}
    for text in (spec.stamp, stamp):
        if isinstance(text, TextStamp | BrandText):
            named.add(text.font)
    fonts: dict[str, FontFile] = {}
    for font in kit.fonts:
        if font_id(font.asset) in named:
            row = await _asset(conn, workspace_id, font.asset)
            fonts[font_id(font.asset)] = FontFile(await read(row["storage_key"]))
    return stamp, fonts


async def _asset(conn: AsyncConnection, workspace_id: str, asset_id: str) -> RowMapping:
    found = (
        (
            await conn.execute(
                select(assets).where(
                    assets.c.workspace_id == workspace_id,
                    assets.c.id == asset_id,
                    assets.c.status == "ready",
                )
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        raise LookupError(f"the brand kit names {asset_id}, which is not a ready upload")
    return found
