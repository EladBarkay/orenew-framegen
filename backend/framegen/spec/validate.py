"""Reading a frame spec, with problems reported by stable codes."""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from framegen.spec.models import FrameSpec


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
    """Pydantic's location as a path into the submitted JSON: a discriminated union adds
    its tag values as steps (``layers, 0, "vector", "bar", "colour"``), which are dropped."""
    path: list[str | int] = []
    node = data
    tags: list[object] = []
    for step in location:
        if isinstance(node, dict):
            if step in tags:  # checked first: a piece's tag "piece" is also a field name
                tags.remove(step)
                continue
            node = node.get(step) if isinstance(step, str) else None
        elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        else:
            node = None
        path.append(step)
        # Only decoration layers are union members, and they always have a kind.
        tags = (
            [node["kind"], node.get("shape")] if isinstance(node, dict) and "kind" in node else []
        )
    return tuple(path)
