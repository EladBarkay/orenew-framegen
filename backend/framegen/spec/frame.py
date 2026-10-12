"""The whole frame spec, and the rules that span its parts (DESIGN.md 4.1)."""

from typing import Annotated, Literal, Self, get_args

from pydantic import BeforeValidator, model_validator
from pydantic_core import PydanticCustomError

from framegen.spec.models import (
    Anchor,
    Aspect,
    Band,
    Bar,
    Decoration,
    Piece,
    SpecModel,
    Stroke,
    Window,
)
from framegen.spec.text import Date, Headline, Orientation, Stamp, slot_in

CORNERS = {anchor for anchor in get_args(Anchor) if "-" in anchor}


def _exact_version(value: object) -> object:
    # Literal compares by equality, and True == 1.0 == 1 in Python.
    if type(value) is not int:
        raise PydanticCustomError("int_type", "Input should be a valid integer")
    return value


class FrameSpec(SpecModel):
    """One frame design."""

    spec_version: Annotated[Literal[1], BeforeValidator(_exact_version)]
    aspect: Aspect
    window: Window
    decoration: Decoration
    headline: Headline | None = None
    date: Date | None = None
    stamp: Stamp | None = None

    @model_validator(mode="after")
    def _archetype_has_its_layers(self) -> Self:
        layers = self.decoration.layers
        pieces = [layer for layer in layers if isinstance(layer, Piece)]
        needs = {
            "stroke": ("a stroke", any(isinstance(layer, Stroke) for layer in layers)),
            "bar": ("a bar or band", any(isinstance(layer, Bar | Band) for layer in layers)),
            "corners": ("a piece at a corner", any(p.anchor in CORNERS for p in pieces)),
            "surround": ("a layer", bool(layers)),
            "scatter": ("two pieces", len(pieces) >= 2),
            "template": ("a piece", bool(pieces)),
        }
        what, present = needs[self.decoration.archetype]
        if not present:
            raise PydanticCustomError(
                "spec_archetype_incomplete",
                "A '{archetype}' decoration needs {what}.",
                {"archetype": self.decoration.archetype, "what": what},
            )
        return self

    @model_validator(mode="after")
    def _one_component_per_slot(self) -> Self:
        components = {"headline": self.headline, "date": self.date, "stamp": self.stamp}
        for orientation in get_args(Orientation):
            taken: dict[str, str] = {}
            for name, component in components.items():
                if component is None:
                    continue
                slot = slot_in(component.slot, orientation)
                if slot == "under-headline" and (name == "headline" or self.headline is None):
                    raise PydanticCustomError(
                        "spec_slot_under_headline",
                        "The {name} is placed under a headline that is not there.",
                        {"name": name},
                    )
                if slot in taken:
                    raise PydanticCustomError(
                        "spec_slot_taken",
                        "The {name} and the {other} are both in '{slot}' ({orientation}).",
                        {
                            "name": name,
                            "other": taken[slot],
                            "slot": slot,
                            "orientation": orientation,
                        },
                    )
                taken[slot] = name
        return self
