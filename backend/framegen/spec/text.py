"""The frame spec's text components: headline, date and stamp (DESIGN.md 4.1 and 4.3).

Text is never part of a piece: the renderer draws it with real fonts, so it stays sharp
and editable. Each component sits in a named slot per orientation.
"""

import datetime
import re
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Discriminator, Field, Tag, model_validator
from pydantic_core import PydanticCustomError

from framegen.spec.models import Color, Fraction, SpecModel

Slot = Literal[
    "top-band",
    "bottom-band",
    "top-start",
    "top-end",
    "bottom-start",
    "bottom-end",
    "under-headline",
    "start-edge",
    "end-edge",
]
"""Named regions. Bands run across the frame; corners hold small items; the edges run
along the side, with the text turned to read upwards (as the owner's stamps do)."""


Orientation = Literal["portrait", "landscape"]


class SlotPerOrientation(SpecModel):
    portrait: Slot
    landscape: Slot


def _placement_kind(value: object) -> str:
    return "name" if isinstance(value, str) else "each"


Placement = Annotated[
    Annotated[Slot, Tag("name")] | Annotated[SlotPerOrientation, Tag("each")],
    Discriminator(_placement_kind),
]
"""A slot name for the same slot in both orientations, or one slot for each."""


def slot_in(placement: Placement, orientation: Orientation) -> Slot:
    if isinstance(placement, SlotPerOrientation):
        return placement.portrait if orientation == "portrait" else placement.landscape
    return placement


FontRef = Annotated[
    str,
    Field(
        pattern=r"^(font_[a-z2-7]{26}|[a-z0-9]+(-[a-z0-9]+)*)$",
        max_length=40,
        description="A workspace font (font_…) or a built-in font by name (heebo, suez-one).",
        examples=["heebo", "amatic-sc-bold"],
    ),
]

_CONTROL = re.compile(
    "[\x00-\x09\x0b-\x1f\x7f-\x9f"  # control characters, but not the line break
    "\u202a-\u202e\u2066-\u2069"  # direction overrides and isolates: they reorder text
    "\u2028\u2029]"  # other line and paragraph separators
)
"""Not allowed in text. The direction marks Hebrew needs (U+200E, U+200F) are allowed."""


def _no_control(value: object) -> object:
    if isinstance(value, str) and _CONTROL.search(value):
        raise PydanticCustomError("spec_text_control", "The text has control characters.")
    return value


def _not_blank(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        raise PydanticCustomError("spec_text_empty", "The text is empty.")
    return value


Text = Annotated[
    str, BeforeValidator(_not_blank), BeforeValidator(_no_control), Field(max_length=200)
]


class TextStyle(SpecModel):
    font: FontRef
    color: Color
    size: Annotated[
        float,
        Field(
            gt=0,
            le=0.25,
            allow_inf_nan=False,
            description="Largest text height, as a share of the frame's shorter side; the "
            "renderer shrinks the text to fit its slot.",
        ),
    ]


class Headline(TextStyle):
    text: Text
    slot: Placement


DATE_FIELDS = {"d", "dd", "M", "MM", "MMM", "MMMM", "yy", "yyyy"}


class GregorianFormat(SpecModel):
    calendar: Literal["gregorian"]
    pattern: str | None = Field(
        default=None,
        pattern=r"^[dMy .,/\-]+$",
        max_length=40,
        description="Unicode date pattern: d or dd, M to MMMM, yy or yyyy, and separators.",
        examples=["dd.MM.yyyy", "d.M.yy", "d MMMM yyyy"],
    )
    style: Literal["short", "medium", "long", "full"] | None = None
    locale: str = Field(default="he", pattern=r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        if (self.pattern is None) == (self.style is None):
            raise PydanticCustomError(
                "spec_date_pattern_or_style", "Give a pattern or a style, not both."
            )
        if self.pattern is not None:
            runs = re.findall("d+|M+|y+", self.pattern)
            if not runs:
                raise PydanticCustomError("spec_date_pattern_empty", "The pattern shows no date.")
            # Each run of a letter is one whole field, so "ddd" is not read as "dd" + "d".
            if any(run not in DATE_FIELDS for run in runs):
                raise PydanticCustomError(
                    "spec_date_pattern_field",
                    "Use d or dd, M to MMMM, and yy or yyyy.",
                )
        return self


class HebrewFormat(SpecModel):
    calendar: Literal["hebrew"]
    style: Literal["day-month-year", "month-year", "year"] = "day-month-year"
    numerals: Literal["hebrew", "digits"] = "hebrew"


DateFormat = Annotated[GregorianFormat | HebrewFormat, Field(discriminator="calendar")]


def _iso_date(value: object) -> object:
    # JSON has no date type: exactly YYYY-MM-DD, nothing looser (no times, no numbers).
    if type(value) is datetime.date:  # already read, as when a spec is validated again
        return value
    if not (isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
        raise PydanticCustomError("date_type", "Input should be a date as YYYY-MM-DD")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise PydanticCustomError("date_from_datetime_parsing", "Not a real date") from error


class Date(TextStyle):
    value: Annotated[
        datetime.date,
        BeforeValidator(_iso_date),
        Field(json_schema_extra={"type": "string", "format": "date"}),
    ]
    after_sunset: bool = Field(
        default=False,
        description="The event is in the evening, so its Hebrew date is the next day's.",
    )
    formats: list[DateFormat] = Field(min_length=1, max_length=3)
    joiner: Annotated[str, BeforeValidator(_no_control)] | None = Field(
        default=" · ",
        max_length=10,
        description="Between formats on one line; null stacks them on separate lines.",
    )
    override: Text | None = Field(
        default=None, description="Text typed by hand, shown instead of the formats."
    )
    slot: Placement


class StampBase(SpecModel):
    slot: Placement
    opacity: Fraction = 1


class MarkSize(SpecModel):
    size: Annotated[
        float,
        Field(
            gt=0,
            le=0.5,
            allow_inf_nan=False,
            description="Longest side, as a share of the frame's shorter side.",
        ),
    ] = 0.08


class BrandKitStamp(StampBase, MarkSize):
    """The workspace's stamp from its brand kit."""

    source: Literal["brand-kit"]


class TextStamp(StampBase, TextStyle):
    """A text stamp given here; its size is a text height, as for the headline."""

    source: Literal["text"]
    text: Text


class ImageStamp(StampBase, MarkSize):
    source: Literal["image"]
    image: str = Field(pattern=r"^ast_[a-z2-7]{26}$")


Stamp = Annotated[BrandKitStamp | TextStamp | ImageStamp, Field(discriminator="source")]
"""The photographer's mark: from the workspace's brand kit, or given here."""
