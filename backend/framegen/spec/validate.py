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
                Problem(location=tuple(item["loc"]), code=item["type"], message=item["msg"])
                for item in error.errors(include_url=False)
            ]
        ) from error
