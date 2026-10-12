"""Reading a frame spec, with problems reported by stable codes."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from framegen.spec.frame import FrameSpec


@dataclass(frozen=True)
class Problem:
    location: tuple[str | int, ...]
    """Path to the field, in the spec's JSON names."""
    code: str
    """Stable: Pydantic's documented error type, or one of the spec's own `spec_…` codes."""
    message: str


class SpecInvalid(ValueError):
    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"the frame spec is not valid: {len(problems)} problem(s)")
        self.problems = problems


def read_spec(data: Any) -> FrameSpec:
    """Validates JSON-like data as a frame spec. Raises SpecInvalid listing every problem."""
    try:
        return FrameSpec.model_validate(data, by_alias=True, by_name=False)
    except ValidationError as error:
        raise SpecInvalid(
            [
                Problem(
                    location=_json_path(data, item["loc"]),
                    code=item["type"],
                    message=item["msg"],
                )
                for item in error.errors(include_url=False)
            ]
        ) from error


def _json_path(data: Any, location: tuple[str | int, ...]) -> tuple[str | int, ...]:
    """Pydantic's location as a path into the submitted JSON. Decoration layers are a
    discriminated union, and Pydantic puts the tags right after a layer's index:
    ``layers, 0, "vector", "bar", "colour"``. Those tag steps are dropped."""
    path: list[str | int] = []
    node = data
    tags: list[object] = []
    for step in location:
        if tags and step == tags[0]:
            tags.pop(0)
            continue
        tags = []
        if isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
            if path[-1:] == ["layers"] and isinstance(node, dict):
                tags = [node.get("kind")]
                if node.get("kind") == "vector":
                    tags.append(node.get("shape"))
        elif isinstance(node, dict) and isinstance(step, str):
            node = node.get(step)
        else:
            node = None
        path.append(step)
    return tuple(path)
