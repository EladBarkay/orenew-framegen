"""Draws a frame spec as one SVG document (DESIGN.md 4.1, 4.4 and 9).

The SVG is rasterised by Chromium (T-12b). Everything is computed here in pixels, so the
same spec, size and images always give the same text, and so the same pixels.

Order: the decoration layers as listed, then the window is cut out of them; layers that
may overlap the window are drawn after the cut, on top, in their own order. Text comes
with T-13.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import quoteattr

from framegen.spec import FrameSpec
from framegen.spec.models import ANCHOR_POINTS, Band, Bar, Layer, Piece, Shape, Stroke, Window
from framegen.spec.text import Orientation

Direction = Literal["rtl", "ltr"]
"""Reading direction: in right-to-left text (Hebrew), start is the right side."""


@dataclass(frozen=True)
class Image:
    """A piece's or a mask's pixels, as the renderer is given them."""

    href: str
    """A data: URL (the renderer loads nothing from the network)."""
    width: int
    height: int


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def grow(self, by: float) -> "Rect":
        return Rect(self.x - by, self.y - by, self.width + 2 * by, self.height + 2 * by)


class MissingImage(ValueError):
    pass


def render_svg(
    spec: FrameSpec,
    orientation: Orientation,
    width: int,
    height: int,
    *,
    direction: Direction = "rtl",
    images: Mapping[str, Image] | None = None,
) -> str:
    """The frame at width x height pixels, with a transparent background. `images` holds
    every piece and window mask the spec names, by ID."""
    if width < 1 or height < 1:
        raise ValueError("the size must be at least 1x1 pixels")
    frame = _Frame(width, height, direction, images or {})
    window = frame.window_rect(spec.window, orientation)
    under = [layer for layer in spec.decoration.layers if not _overlaps(layer)]
    over = [layer for layer in spec.decoration.layers if _overlaps(layer)]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<defs>",
        *frame.window_cut(spec.window, window),
        "</defs>",
        '<g mask="url(#window-cut)">',
        *(frame.layer(layer, spec.window, window) for layer in under),
        "</g>",
        *(frame.layer(layer, spec.window, window) for layer in over),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def _overlaps(layer: Layer) -> bool:
    return layer.overlaps_window


def _n(value: float) -> str:
    """Numbers with three decimals at most, written the same way every time."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _paint(color: str, opacity: float) -> str:
    return f'fill="{color}"' + (f' opacity="{_n(opacity)}"' if opacity != 1 else "")


class _Frame:
    def __init__(
        self, width: int, height: int, direction: Direction, images: Mapping[str, Image]
    ) -> None:
        self.width = width
        self.height = height
        self.short = min(width, height)
        self.rtl = direction == "rtl"
        self.images = images

    def x(self, inline: float) -> float:
        """A share of the width from the start side, in pixels from the left."""
        return (1 - inline) * self.width if self.rtl else inline * self.width

    def image(self, image_id: str) -> Image:
        try:
            return self.images[image_id]
        except KeyError:
            raise MissingImage(f"no image given for {image_id}") from None

    # The window.

    def window_rect(self, window: Window, orientation: Orientation) -> Rect:
        inset = getattr(window, orientation).inset
        left, right = (inset.end, inset.start) if self.rtl else (inset.start, inset.end)
        return Rect(
            left * self.width,
            inset.top * self.height,
            (1 - left - right) * self.width,
            (1 - inset.top - inset.bottom) * self.height,
        )

    def window_cut(self, window: Window, rect: Rect) -> Iterator[str]:
        """A mask that is white (kept) everywhere but the window."""
        yield (
            f'<mask id="window-cut" maskUnits="userSpaceOnUse" x="0" y="0" '
            f'width="{self.width}" height="{self.height}">'
        )
        yield f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#ffffff"/>'
        if window.shape == "mask":
            assert window.mask is not None
            # The mask image's alpha is the window: drawn black where it is opaque.
            yield (
                '<filter id="alpha-to-black"><feColorMatrix type="matrix" '
                'values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0"/></filter>'
            )
            yield (
                f"<image href={quoteattr(self.image(window.mask).href)} "
                f'x="{_n(rect.x)}" y="{_n(rect.y)}" width="{_n(rect.width)}" '
                f'height="{_n(rect.height)}" preserveAspectRatio="none" '
                f'filter="url(#alpha-to-black)"/>'
            )
        else:
            yield self.window_shape(window, rect, 'fill="#000000"')
        yield "</mask>"

    def window_shape(
        self, window: Window, rect: Rect, paint: str, radius: float | None = None
    ) -> str:
        """The window's outline around `rect` (a mask window is outlined as its box).
        `radius`, in pixels, replaces a rounded window's own."""
        x, y, w, h = rect.x, rect.y, rect.width, rect.height
        if window.shape == "oval":
            return (
                f'<ellipse cx="{_n(x + w / 2)}" cy="{_n(y + h / 2)}" rx="{_n(w / 2)}" '
                f'ry="{_n(h / 2)}" {paint}/>'
            )
        if window.shape == "arch":
            # A rectangle whose top is a half ellipse as wide as the window.
            ry = min(w / 2, h)
            return (
                f'<path d="M {_n(x)} {_n(y + h)} L {_n(x)} {_n(y + ry)} '
                f"A {_n(w / 2)} {_n(ry)} 0 0 1 {_n(x + w)} {_n(y + ry)} "
                f'L {_n(x + w)} {_n(y + h)} Z" {paint}/>'
            )
        if radius is None:
            radius = (window.radius or 0) * min(w, h) if window.shape == "rounded" else 0
        corner = f' rx="{_n(radius)}"' if radius else ""
        return f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{corner} {paint}/>'

    # Layers.

    def layer(self, layer: Layer, window: Window, window_rect: Rect) -> str:
        match layer:
            case Stroke():
                return self.stroke(layer, window, window_rect)
            case Band():
                return self.strip(layer, 0, layer.thickness)
            case Bar():
                return self.strip(layer, layer.distance, layer.thickness)
            case Shape():
                return self.shape(layer)
            case Piece():
                return self.piece(layer)

    def stroke(self, stroke: Stroke, window: Window, window_rect: Rect) -> str:
        width = stroke.width * self.short
        paint = f'fill="none" stroke="{stroke.color}" stroke-width="{_n(width)}"' + (
            f' opacity="{_n(stroke.opacity)}"' if stroke.opacity != 1 else ""
        )
        middle = stroke.offset * self.short + width / 2  # from the edge to the line's centre
        if stroke.around == "frame":
            inner = Rect(0, 0, self.width, self.height).grow(-middle)
            return (
                f'<rect x="{_n(inner.x)}" y="{_n(inner.y)}" width="{_n(inner.width)}" '
                f'height="{_n(inner.height)}" {paint}/>'
            )
        # Around the window: its outline moved outwards, corners kept parallel.
        radius = None
        if window.shape == "rounded" and window.radius is not None:
            radius = window.radius * min(window_rect.width, window_rect.height) + middle
        return self.window_shape(window, window_rect.grow(middle), paint, radius)

    def strip(self, layer: Band | Bar, distance: float, thickness: float) -> str:
        across = self.height if layer.edge in ("top", "bottom") else self.width
        near, size = distance * across, thickness * across
        side: str = layer.edge
        if side in ("start", "end"):
            side = "right" if (side == "start") == self.rtl else "left"
        rect = {
            "top": Rect(0, near, self.width, size),
            "bottom": Rect(0, self.height - near - size, self.width, size),
            "left": Rect(near, 0, size, self.height),
            "right": Rect(self.width - near - size, 0, size, self.height),
        }[side]
        return (
            f'<rect x="{_n(rect.x)}" y="{_n(rect.y)}" width="{_n(rect.width)}" '
            f'height="{_n(rect.height)}" {_paint(layer.color, layer.opacity)}/>'
        )

    def shape(self, shape: Shape) -> str:
        box = shape.box
        w, h = box.width * self.width, box.height * self.height
        left = self.x(box.x + box.width) if self.rtl else self.x(box.x)
        top = box.y * self.height
        cx, cy = left + w / 2, top + h / 2
        turn = f' transform="rotate({_n(shape.rotate)} {_n(cx)} {_n(cy)})"' if shape.rotate else ""
        paint = _paint(shape.color, shape.opacity)
        if shape.shape == "ellipse":
            return (
                f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(w / 2)}" ry="{_n(h / 2)}" '
                f"{paint}{turn}/>"
            )
        return (
            f'<rect x="{_n(left)}" y="{_n(top)}" width="{_n(w)}" height="{_n(h)}" {paint}{turn}/>'
        )

    def piece(self, piece: Piece) -> str:
        image = self.image(piece.piece)
        scale = piece.size * self.short / max(image.width, image.height)
        w, h = image.width * scale, image.height * scale
        inline, block = ANCHOR_POINTS[piece.anchor]
        # The piece's own anchor point sits on the frame's anchor point (moved by the offset).
        ax, ay = self.x(inline + piece.offset.x), (block + piece.offset.y) * self.height
        left = ax - ((1 - inline) * w if self.rtl else inline * w)
        top = ay - block * h
        cx, cy = left + w / 2, top + h / 2
        steps = []
        if piece.rotate:
            steps.append(f"rotate({_n(piece.rotate)} {_n(cx)} {_n(cy)})")
        if piece.mirror != "none":
            sx, sy = (-1, 1) if piece.mirror == "inline" else (1, -1)
            steps.append(
                f"translate({_n(cx)} {_n(cy)}) scale({sx} {sy}) translate({_n(-cx)} {_n(-cy)})"
            )
        transform = f' transform="{" ".join(steps)}"' if steps else ""
        return (
            f'<image href={quoteattr(image.href)} x="{_n(left)}" y="{_n(top)}" '
            f'width="{_n(w)}" height="{_n(h)}" preserveAspectRatio="none"{transform}/>'
        )
