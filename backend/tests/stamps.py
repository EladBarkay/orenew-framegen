"""Helpers for the stamp tests (test_render_stamps, and the Chromium ones)."""

import base64
import io
from typing import Any

from PIL import Image as PILImage

from framegen.render.svg import Image
from framegen.spec import read_spec

LOGO = "ast_" + "l" * 26


def png(width: int, height: int, color: str = "#ff0000") -> Image:
    out = io.BytesIO()
    PILImage.new("RGBA", (width, height), color).save(out, "PNG")
    href = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()
    return Image(href, width, height)


def spec(stamp: dict[str, Any]) -> Any:
    inset = {"top": 0.1, "bottom": 0.2, "start": 0.1, "end": 0.1}
    return read_spec({
        "specVersion": 1, "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {"shape": "rectangle", "portrait": {"inset": inset},
                   "landscape": {"inset": inset}},
        "decoration": {"archetype": "surround", "layers": [
            {"kind": "vector", "shape": "rectangle", "color": "#336699",
             "box": {"x": 0, "y": 0, "width": 1, "height": 1}}]},
        "stamp": stamp,
    })  # fmt: skip
