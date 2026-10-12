"""The frame spec: window and decoration (DESIGN.md sections 4.1 and 4.4).

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


class SpecModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True
    )


Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
"""A share of the frame: 0 is nothing, 1 is all of it."""

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
        if 1 - self.top - self.bottom < MIN_WINDOW or 1 - self.start - self.end < MIN_WINDOW:
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
    radius: Fraction | None = Field(
        default=None, description="Corner radius for 'rounded', as a share of the shorter side."
    )
    mask: str | None = Field(
        default=None,
        pattern=r"^ast_[0-9A-Za-z]+$",
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
        if self.radius is not None and self.radius > 0.5:
            raise PydanticCustomError(
                "spec_window_radius", "The radius is at most half the shorter side."
            )
        if (self.mask is not None) != (self.shape == "mask"):
            raise PydanticCustomError(
                "spec_window_mask", "A mask is required for 'mask', and only there."
            )
        return self


Edge = Literal["top", "bottom", "start", "end"]
Anchor = Literal[
    "top-start", "top", "top-end", "start", "center", "end", "bottom-start", "bottom", "bottom-end"
]
Opacity = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Thickness = Annotated[float, Field(gt=0, le=0.5, allow_inf_nan=False)]


class Stroke(SpecModel):
    """A line around the window or along the frame's outer edge."""

    kind: Literal["vector"]
    shape: Literal["stroke"]
    around: Literal["window", "frame"] = "window"
    width: Annotated[float, Field(gt=0, le=0.1, allow_inf_nan=False)]
    offset: Fraction = Field(default=0, description="Gap between the line and what it surrounds.")
    color: Color
    opacity: Opacity = 1


class Band(SpecModel):
    """A solid strip flush with one edge of the frame, across its full length."""

    kind: Literal["vector"]
    shape: Literal["band"]
    edge: Edge
    thickness: Thickness
    color: Color
    opacity: Opacity = 1


class Bar(SpecModel):
    """A strip parallel to one edge, at a distance from it (it may cross the window's
    edge, as in a caption bar)."""

    kind: Literal["vector"]
    shape: Literal["bar"]
    edge: Edge
    distance: Fraction = Field(description="From the edge to the bar's near side.")
    thickness: Thickness
    color: Color
    opacity: Opacity = 1

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.distance + self.thickness > 1:
            raise PydanticCustomError("spec_outside_frame", "The bar ends outside the frame.")
        return self


class Box(SpecModel):
    """A rectangle in frame fractions, from the top-start corner."""

    x: Fraction
    y: Fraction
    width: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise PydanticCustomError("spec_outside_frame", "The box ends outside the frame.")
        return self


class Shape(SpecModel):
    """A filled rectangle or ellipse."""

    kind: Literal["vector"]
    shape: Literal["rectangle", "ellipse"]
    box: Box
    rotate: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] = 0
    color: Color
    opacity: Opacity = 1


class Offset(SpecModel):
    x: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] = 0
    y: Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)] = 0


class Piece(SpecModel):
    """A raster artwork piece (with its own transparency), placed by anchor."""

    kind: Literal["piece"]
    piece: str = Field(pattern=r"^pc_[0-9A-Za-z]+$")
    anchor: Anchor
    size: Annotated[
        float,
        Field(
            gt=0,
            le=1,
            allow_inf_nan=False,
            description="The piece's longer side, as a share of the frame's shorter side.",
        ),
    ]
    offset: Offset = Offset()
    rotate: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)] = 0
    mirror: Literal["none", "inline", "block"] = "none"
    overlaps_window: bool = Field(
        default=False,
        description="Whether the piece may cover the window's edge (DESIGN.md 4.4). If not, "
        "the window is cut through it.",
    )


VectorLayer = Annotated[Stroke | Band | Bar | Shape, Field(discriminator="shape")]
Layer = Annotated[VectorLayer | Piece, Field(discriminator="kind")]


class Decoration(SpecModel):
    archetype: Literal["stroke", "bar", "corners", "surround", "scatter", "template"]
    layers: list[Layer] = Field(
        max_length=64, description="Drawn in order: the first is at the bottom."
    )


class FrameSpec(SpecModel):
    """One frame design. Headline, date and stamp are added in T-11b."""

    spec_version: Literal[1]
    aspect: Aspect
    window: Window
    decoration: Decoration
