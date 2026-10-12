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
    """Validates JSON-like data as a frame spec. Raises SpecInvalid listing every field
    problem; the rules across fields run once the fields are valid, and the first rule
    broken is reported."""
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
    """Pydantic's location as a path into the submitted JSON. Each union in the spec adds
    its tags as steps right after the union's own place; those steps are dropped."""
    path: list[str | int] = []
    node = data
    tags: list[object] = []
    for step in location:
        if tags and step == tags[0]:
            tags.pop(0)
            continue
        if isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        elif isinstance(node, dict) and isinstance(step, str):
            node = node.get(step)
        else:
            node = None
        path.append(step)
        tags = _union_tags(path, node)
    return tuple(path)


def _union_tags(path: list[str | int], node: Any) -> list[object]:
    """The tags Pydantic puts after this place, if it is a union (in this order)."""
    if path[-1] == "slot":
        return ["name" if isinstance(node, str) else "each"]
    if not isinstance(node, dict):
        return []
    if path[-2:-1] == ["layers"] and isinstance(path[-1], int):
        return [node.get("kind"), *([node.get("shape")] if node.get("kind") == "vector" else [])]
    if path[-2:-1] == ["formats"] and isinstance(path[-1], int):
        return [node.get("calendar")]
    if path == ["stamp"]:
        return [node.get("source")]
    return []
