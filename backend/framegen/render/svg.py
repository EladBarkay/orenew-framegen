"""Draws a frame spec as one SVG document (DESIGN.md 4.1, 4.4 and 9).

The SVG is rasterised by Chromium (T-12b). Everything is computed here in pixels, so the
same spec, size and images always give the same text, and so the same pixels.

Layers are drawn in their order, the first at the bottom. Each is cut by the window,
except layers marked to overlap it. The headline and a text stamp go on top, in their
slots, with the fonts embedded (render.text); dates come with T-14 and image stamps with
T-15.

Only placement follows the reading direction (start is the right side in Hebrew).
Rotation is clockwise and artwork is drawn as given in both directions: flipping it is
the spec's `mirror`, since not every piece can be mirrored (a bottle with a label).

Each SVG is meant to be drawn on its own, as a document or an <img>: its mask and filter
IDs are fixed, so two inline in one page would share them.
"""

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal
from xml.sax.saxutils import escape, quoteattr

from framegen.render.measure import fit
from framegen.render.text import (
    HEADLINE_SHARE,
    MARGIN,
    Area,
    FontFile,
    Fonts,
    FontUse,
    slot_area,
    text_direction,
)
from framegen.spec import FrameSpec
from framegen.spec.models import (
    ANCHOR_POINTS,
    Band,
    Bar,
    Layer,
    Piece,
    Shape,
    Stroke,
    Window,
    ratio,
)
from framegen.spec.text import Orientation, Slot, TextStamp, slot_in, visible

Direction = Literal["rtl", "ltr"]
"""Reading direction: in right-to-left text (Hebrew), start is the right side."""

IMAGE_HREF = re.compile(r"data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/]*={0,2}\Z")


@dataclass(frozen=True)
class Image:
    """A piece's or a mask's pixels, as the renderer is given them."""

    href: str
    """A data: URL of a PNG, JPEG, WebP or SVG: the renderer loads nothing from the
    network or the disk."""
    width: int
    height: int

    def __post_init__(self) -> None:
        if not IMAGE_HREF.match(self.href):
            raise ValueError("an image must be a data: URL of a PNG, JPEG, WebP or SVG")
        if self.width < 1 or self.height < 1:
            raise ValueError("an image must be at least 1x1 pixels")


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
    fonts: Mapping[str, FontFile] | None = None,
) -> str:
    """The frame at width x height pixels, with a transparent background. `images` holds
    every piece and window mask the spec names, and `fonts` every workspace font, by ID."""
    if width < 1 or height < 1:
        raise ValueError("the size must be at least 1x1 pixels")
    if direction not in ("rtl", "ltr"):
        raise ValueError(f"the direction is 'rtl' or 'ltr', not {direction!r}")
    if orientation not in ("portrait", "landscape"):
        raise ValueError(f"the orientation is 'portrait' or 'landscape', not {orientation!r}")
    aspect = getattr(spec.aspect, orientation)
    if abs(width - height * ratio(aspect)) > 1:
        raise ValueError(f"{width}x{height} pixels is not the {orientation} aspect {aspect}")
    frame = _Frame(width, height, direction, images or {})
    window = frame.window_rect(spec.window, orientation)
    if window.width < 1 or window.height < 1:
        raise ValueError(f"{width}x{height} pixels is too small for the window")
    used = Fonts(fonts or {})
    texts = list(frame.texts(spec, orientation, window, used))
    style = used.style()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<defs>",
        *([style] if style else []),
        *frame.window_cut(spec.window, window),
        "</defs>",
        *(
            # A group carries the cut, so a layer's own transform does not move it.
            element if layer.overlaps_window else f'<g mask="url(#window-cut)">{element}</g>'
            for layer in spec.decoration.layers
            for element in [frame.layer(layer, spec.window, window)]
        ),
        # Text stays out of the window too, whatever its slot.
        *(f'<g mask="url(#window-cut)">{text}</g>' for text in texts),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def _px(value: float) -> int:
    """To the nearest whole pixel, halves up (not to even), so both directions agree."""
    return math.floor(value + 0.5)


def _n(value: float) -> str:
    """Numbers with three decimals at most, written the same way every time."""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _opacity(opacity: float) -> str:
    return f' opacity="{_n(opacity)}"' if opacity != 1 else ""


def _paint(color: str, opacity: float) -> str:
    return f'fill="{color}"' + _opacity(opacity)


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
        # Whole pixels, so no pixel is half window and half decoration.
        x0, x1 = _px(left * self.width), _px((1 - right) * self.width)
        y0, y1 = _px(inset.top * self.height), _px((1 - inset.bottom) * self.height)
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def window_cut(self, window: Window, rect: Rect) -> Iterator[str]:
        """A mask that is white (kept) everywhere but the window."""
        yield (
            f'<mask id="window-cut" maskUnits="userSpaceOnUse" x="0" y="0" '
            f'width="{self.width}" height="{self.height}">'
        )
        yield f'<rect x="0" y="0" width="{self.width}" height="{self.height}" fill="#ffffff"/>'
        if window.shape == "mask":
            assert window.mask is not None
            # The mask image's alpha is the window: drawn black where it is opaque, keeping
            # its proportions and centred, so it is the same shape in both orientations.
            yield (
                '<filter id="alpha-to-black"><feColorMatrix type="matrix" '
                'values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0"/>'
                # Half or more opaque is window, the rest is not: no pixel is in between.
                '<feComponentTransfer><feFuncA type="discrete" tableValues="0 1"/>'
                "</feComponentTransfer></filter>"
            )
            yield (
                f"<image href={quoteattr(self.image(window.mask).href)} "
                f'x="{_n(rect.x)}" y="{_n(rect.y)}" width="{_n(rect.width)}" '
                f'height="{_n(rect.height)}" preserveAspectRatio="xMidYMid meet" '
                f'filter="url(#alpha-to-black)"/>'
            )
        else:
            # Crisp edges: each pixel is window or not, so the window has alpha exactly 0
            # (DESIGN.md 4.4) whatever its shape.
            yield self.window_shape(window, rect, 'fill="#000000" shape-rendering="crispEdges"')
        yield "</mask>"

    def window_shape(self, window: Window, rect: Rect, paint: str, grow: float = 0) -> str:
        """The window's outline around `rect`, moved outwards by `grow` pixels with its
        corners kept parallel (a mask window is outlined as its box)."""
        radius = (window.radius or 0) * min(rect.width, rect.height) + grow
        rect = rect.grow(grow)
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
        corner = f' rx="{_n(radius)}"' if window.shape == "rounded" and radius else ""
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
        paint = f'fill="none" stroke="{stroke.color}" stroke-width="{_n(width)}"' + _opacity(
            stroke.opacity
        )
        middle = stroke.offset * self.short + width / 2  # from the edge to the line's centre
        if stroke.around == "frame":
            inner = Rect(0, 0, self.width, self.height).grow(-middle)
            return (
                f'<rect x="{_n(inner.x)}" y="{_n(inner.y)}" width="{_n(inner.width)}" '
                f'height="{_n(inner.height)}" {paint}/>'
            )
        return self.window_shape(window, window_rect, paint, grow=middle)

    def strip(self, layer: Band | Bar, distance: float, thickness: float) -> str:
        across = self.height if layer.edge in ("top", "bottom") else self.width
        # Whole pixels, like the window, so a band meeting it leaves no half-covered seam.
        near = _px(distance * across)
        size = _px((distance + thickness) * across) - near
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

    # Text.

    def texts(
        self, spec: FrameSpec, orientation: Orientation, window: Rect, fonts: Fonts
    ) -> Iterator[str]:
        """The headline and a text stamp, each in its slot."""
        box = (window.x, window.y, window.width, window.height)
        # Every component's slot counts, including those not drawn yet (dates, T-14), so
        # adding them later does not move the others.
        taken = [
            slot_in(part.slot, orientation)
            for part in (spec.headline, spec.date, spec.stamp)
            if part is not None
        ]

        def area_of(slot: Slot) -> Area:
            return slot_area(slot, self.width, self.height, box, self.rtl, taken)

        under: Area | None = None
        if spec.headline is not None:
            headline = spec.headline
            area = area_of(slot_in(headline.slot, orientation))
            if "under-headline" in taken:
                area, under = area.split(HEADLINE_SHARE, gap=MARGIN * self.short)
            yield self.text(
                headline.text, area, fonts.use(headline.font), headline.size, headline.color, 1
            )
        stamp = spec.stamp
        if isinstance(stamp, TextStamp):
            slot = slot_in(stamp.slot, orientation)
            if slot == "under-headline":
                assert under is not None  # the spec has a headline (FrameSpec checks it)
                area = under
            else:
                area = area_of(slot)
            yield self.text(
                stamp.text, area, fonts.use(stamp.font), stamp.size, stamp.color, stamp.opacity
            )

    def text(
        self, text: str, area: Area, font: FontUse, size: float, color: str, opacity: float
    ) -> str:
        """The text fitted to its area (measure.fit), its lines centred together;
        `size` is a share of the shorter side. Each line is a paragraph, with its own
        direction."""
        cx, cy = area.x + area.width / 2, area.y + area.height / 2
        turn = "" if area.upright else f' transform="rotate(-90 {_n(cx)} {_n(cy)})"'
        # Blank lines would only push the text off-centre.
        lines = [line for line in text.split("\n") if any(visible(c) for c in line)]
        layout = fit(lines, font.measure, area.length, area.depth, size * self.short)
        return "".join(
            f'<text x="{_n(cx)}" y="{_n(cy + baseline)}" text-anchor="middle" '
            f'direction="{text_direction(line, "rtl" if self.rtl else "ltr")}" '
            f'font-family="{font.family}" font-weight="{font.weight}" '
            f'font-size="{_n(layout.size)}" {_paint(color, opacity)}{turn} '
            f'style="white-space:pre;font-synthesis:none">{escape(line)}</text>'
            for line, baseline in zip(layout.lines, layout.baselines, strict=True)
        )
