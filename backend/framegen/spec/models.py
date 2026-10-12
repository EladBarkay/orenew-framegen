"""The frame spec's building blocks: window and decoration (DESIGN.md 4.1 and 4.4).

All geometry is relative: fractions of the frame, so one spec draws at any size. JSON
names are camelCase, as in DESIGN.md; unknown fields are rejected, so a typo is an error
rather than a silently ignored setting.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

SPEC_VERSION = 1

MIN_WINDOW = 0.2
"""The window is at least this fraction of the frame's width and of its height."""

TOLERANCE = 1e-9
"""Sums of fractions are compared with this slack, so 1 - 0.8 counts as 0.2."""


class SpecModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        # No coercion: "0.5" or true is not a number, as in the JSON Schema.
        strict=True,
    )


Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
"""A share of the frame: 0 is nothing, 1 is all of it. Also used for opacity."""

PositiveFraction = Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

Rotation = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
"""Degrees, clockwise."""

Color = Annotated[
    str,
    Field(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$", examples=["#c9a24a", "#00000080"]),
]
"""sRGB as #rrggbb, or #rrggbbaa with alpha."""

Ratio = Annotated[
    str,
    Field(pattern=r"^[1-9][0-9]{0,3}:[1-9][0-9]{0,3}$", examples=["2:3", "3:4"]),
]
"""Width to height, in whole numbers."""


def ratio(value: str) -> float:
    width, height = value.split(":")
    return int(width) / int(height)


class Aspect(SpecModel):
    """The frame's proportions in each orientation; output presets give the pixel size."""

    portrait: Ratio
    landscape: Ratio

    @model_validator(mode="after")
    def _orientations(self) -> Self:
        if ratio(self.portrait) > 1 or ratio(self.landscape) < 1:
            raise PydanticCustomError(
                "spec_aspect_orientation",
                "The portrait aspect must not be wider than tall, nor the landscape one "
                "taller than wide.",
            )
        return self


class Insets(SpecModel):
    """Distances from the frame's edges to the window. `start` and `end` follow the
    reading direction (start is the right side in Hebrew)."""

    top: Fraction
    bottom: Fraction
    start: Fraction
    end: Fraction

    @model_validator(mode="after")
    def _room_for_window(self) -> Self:
        limit = MIN_WINDOW - TOLERANCE
        if 1 - self.top - self.bottom < limit or 1 - self.start - self.end < limit:
            raise PydanticCustomError(
                "spec_window_too_small",
                "The insets leave the window less than {minimum} of the frame.",
                {"minimum": MIN_WINDOW},
            )
        return self


class WindowPlacement(SpecModel):
    inset: Insets


class Window(SpecModel):
    """The one photo window. It is cut after every layer is drawn, so it is always fully
    transparent (alpha 0) except where a layer is allowed to overlap it."""

    shape: Literal["rectangle", "rounded", "arch", "oval", "mask"]
    radius: Annotated[float, Field(ge=0, le=0.5, allow_inf_nan=False)] | None = Field(
        default=None,
        description="Corner radius for 'rounded', as a share of the window's own shorter "
        "side: 0.5 makes the short sides fully round.",
    )
    mask: str | None = Field(
        default=None,
        pattern=r"^ast_[a-z2-7]{26}$",
        description="For 'mask': the asset whose alpha is the window's shape.",
    )
    portrait: WindowPlacement
    landscape: WindowPlacement

    @model_validator(mode="after")
    def _shape_settings(self) -> Self:
        if (self.radius is not None) != (self.shape == "rounded"):
            raise PydanticCustomError(
                "spec_window_radius", "A radius is required for 'rounded', and only there."
            )
        if (self.mask is not None) != (self.shape == "mask"):
            raise PydanticCustomError(
                "spec_window_mask", "A mask is required for 'mask', and only there."
            )
        return self


Edge = Literal["top", "bottom", "start", "end"]

ANCHOR_POINTS: dict[str, tuple[float, float]] = {
    "top-start": (0, 0), "top": (0.5, 0), "top-end": (1, 0),
    "start": (0, 0.5), "center": (0.5, 0.5), "end": (1, 0.5),
    "bottom-start": (0, 1), "bottom": (0.5, 1), "bottom-end": (1, 1),
}  # fmt: skip
"""Where each anchor is, as (inline, block) fractions from the top-start corner."""
Anchor = Literal[
    "top-start", "top", "top-end", "start", "center", "end", "bottom-start", "bottom", "bottom-end"
]
Thickness = Annotated[float, Field(gt=0, le=0.5, allow_inf_nan=False)]


class LayerBase(SpecModel):
    overlaps_window: bool = Field(
        default=False,
        description="Whether the layer may cover the photo window (DESIGN.md 4.4), as a "
        "caption bar over the photo or a flower over its corner does. If not, the window "
        "is cut through it.",
    )


class Stroke(LayerBase):
    """A line around the window, or along the frame's outer edge. `offset` is the gap
    to what it surrounds: outwards from the window, inwards from the frame's edge. Width
    and offset are shares of the frame's shorter side. A window stroke that reaches past
    the frame is clipped there."""

    kind: Literal["vector"]
    shape: Literal["stroke"]
    around: Literal["window", "frame"] = "window"
    width: Annotated[float, Field(gt=0, le=0.1, allow_inf_nan=False)]
    offset: Fraction = Field(default=0, description="Gap between the line and what it surrounds.")
    color: Color
    opacity: Fraction = 1

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.around == "frame" and self.offset + self.width > 0.5 + TOLERANCE:
            raise PydanticCustomError("spec_outside_frame", "The stroke ends outside the frame.")
        return self


class Band(LayerBase):
    """A solid strip flush with one edge of the frame, across its full length. Its
    thickness is a share of the frame's size across that edge (the height, for the top
    and bottom edges)."""

    kind: Literal["vector"]
    shape: Literal["band"]
    edge: Edge
    thickness: Thickness
    color: Color
    opacity: Fraction = 1


class Bar(LayerBase):
    """A strip parallel to one edge, at a distance from it (it may cross the window's
    edge, as in a caption bar). Distance and thickness are shares of the frame's size
    across that edge."""

    kind: Literal["vector"]
    shape: Literal["bar"]
    edge: Edge
    distance: Fraction = Field(description="From the edge to the bar's near side.")
    thickness: Thickness
    color: Color
    opacity: Fraction = 1

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.distance + self.thickness > 1 + TOLERANCE:
            raise PydanticCustomError("spec_outside_frame", "The bar ends outside the frame.")
        return self


class Box(SpecModel):
    """A rectangle from the frame's top-start corner: x and width are shares of the
    frame's width, y and height of its height."""

    x: Fraction
    y: Fraction
    width: PositiveFraction
    height: PositiveFraction

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.x + self.width > 1 + TOLERANCE or self.y + self.height > 1 + TOLERANCE:
            raise PydanticCustomError("spec_outside_frame", "The box ends outside the frame.")
        return self


class Shape(LayerBase):
    """A filled rectangle or ellipse. It is rotated about its box's centre; parts that a
    rotation takes past the frame are clipped."""

    kind: Literal["vector"]
    shape: Literal["rectangle", "ellipse"]
    box: Box
    rotate: Rotation = 0
    color: Color
    opacity: Fraction = 1


class Offset(SpecModel):
    """A move from the anchor: x towards the end (a share of the frame's width), y
    downwards (a share of its height)."""

    x: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] = 0
    y: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] = 0


class Piece(LayerBase):
    """A raster artwork piece (with its own transparency), placed by anchor."""

    kind: Literal["piece"]
    piece: str = Field(pattern=r"^pc_[a-z2-7]{26}$")
    anchor: Anchor
    size: Annotated[
        PositiveFraction,
        Field(description="The piece's longer side, as a share of the frame's shorter side."),
    ]
    offset: Offset = Offset()
    rotate: Rotation = 0
    mirror: Literal["none", "inline", "block"] = "none"

    @model_validator(mode="after")
    def _anchor_inside(self) -> Self:
        x = ANCHOR_POINTS[self.anchor][0] + self.offset.x
        y = ANCHOR_POINTS[self.anchor][1] + self.offset.y
        if not (-TOLERANCE <= x <= 1 + TOLERANCE and -TOLERANCE <= y <= 1 + TOLERANCE):
            raise PydanticCustomError(
                "spec_outside_frame", "The offset moves the piece's anchor outside the frame."
            )
        return self


VectorLayer = Annotated[Stroke | Band | Bar | Shape, Field(discriminator="shape")]
Layer = Annotated[VectorLayer | Piece, Field(discriminator="kind")]


class Decoration(SpecModel):
    archetype: Literal["stroke", "bar", "corners", "surround", "scatter", "template"]
    layers: list[Layer] = Field(
        max_length=64, description="Drawn in order: the first is at the bottom."
    )
