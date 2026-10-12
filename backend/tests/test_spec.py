import json
from pathlib import Path
from typing import Any

import pytest

from framegen.spec import FrameSpec, SpecInvalid, read_spec
from framegen.spec import schema as spec_schema
from framegen.spec.models import Bar, Piece, Stroke

PIECE = "pc_" + "a2" * 13
MASK = "ast_" + "b3" * 13
SCHEMA_FILE = Path(__file__).parents[2] / "schemas" / "frame-spec.schema.json"


def example() -> dict[str, Any]:
    """The bar frame of attachments/23.9.26, as a spec."""
    return {
        "specVersion": 1,
        "aspect": {"portrait": "2:3", "landscape": "3:2"},
        "window": {
            "shape": "rectangle",
            "portrait": {"inset": {"top": 0, "bottom": 0, "start": 0, "end": 0}},
            "landscape": {"inset": {"top": 0, "bottom": 0, "start": 0, "end": 0}},
        },
        "decoration": {
            "archetype": "bar",
            "layers": [
                {
                    "kind": "vector",
                    "shape": "bar",
                    "edge": "bottom",
                    "distance": 0.09,
                    "thickness": 0.074,
                    "color": "#ffffff",
                },
                {
                    "kind": "vector",
                    "shape": "stroke",
                    "around": "frame",
                    "width": 0.004,
                    "color": "#000000",
                    "opacity": 0.5,
                },
                {
                    "kind": "vector",
                    "shape": "ellipse",
                    "box": {"x": 0.4, "y": 0.1, "width": 0.2, "height": 0.1},
                    "color": "#ff000080",
                },
                {
                    "kind": "piece",
                    "piece": PIECE,
                    "anchor": "bottom-start",
                    "size": 0.1,
                    "offset": {"x": 0.03, "y": -0.07},
                    "mirror": "inline",
                    "overlapsWindow": True,
                },
            ],
        },
    }


def problems(data: dict[str, Any]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(SpecInvalid) as caught:
        read_spec(data)
    return [(problem.location, problem.code) for problem in caught.value.problems]


def with_change(path: list[str | int], value: Any) -> dict[str, Any]:
    data = example()
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if value is DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


DELETE = object()


def test_a_valid_spec_reads_and_round_trips() -> None:
    spec = read_spec(example())
    assert isinstance(spec, FrameSpec)
    layers = spec.decoration.layers
    assert [type(layer) for layer in layers[:2]] == [Bar, Stroke]
    assert isinstance(layers[3], Piece) and layers[3].overlaps_window
    inset = spec.window.portrait.inset
    assert (inset.start, inset.end) == (0, 0)
    # Written out with the JSON names, it reads back to the same spec.
    assert read_spec(json.loads(spec.model_dump_json(by_alias=True))) == spec


def test_python_names_are_not_accepted_in_json() -> None:
    data = example()
    data["spec_version"] = data.pop("specVersion")
    assert ((), "missing") not in problems(data)
    assert (("spec_version",), "extra_forbidden") in problems(data)


def test_unknown_fields_are_rejected() -> None:
    data = with_change(["decoration", "layers", 0, "colour"], "#ffffff")
    assert problems(data) == [(("decoration", "layers", 0, "colour"), "extra_forbidden")]


def test_every_problem_is_reported_at_once() -> None:
    data = example()
    data["specVersion"] = 2
    data["decoration"]["layers"][0]["color"] = "white"
    codes = {code for _, code in problems(data)}
    assert codes == {"literal_error", "string_pattern_mismatch"}


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (["aspect", "portrait"], "3:2", "spec_aspect_orientation"),
        (["aspect", "landscape"], "2:3", "spec_aspect_orientation"),
        (["aspect", "portrait"], "0:3", "string_pattern_mismatch"),
        (
            ["window", "portrait", "inset"],
            {"top": 0.5, "bottom": 0.35, "start": 0, "end": 0},
            "spec_window_too_small",
        ),
        (
            ["window", "landscape", "inset"],
            {"top": 0, "bottom": 0, "start": 0.5, "end": 0.4},
            "spec_window_too_small",
        ),
        (["window", "portrait", "inset", "end"], DELETE, "missing"),
        (["window", "portrait", "inset", "top"], -0.1, "greater_than_equal"),
        (["window", "portrait", "inset", "top"], float("nan"), "finite_number"),
        (["window", "shape"], "rounded", "spec_window_radius"),
        (["window", "radius"], 0.1, "spec_window_radius"),
        (["window", "shape"], "mask", "spec_window_mask"),
        (["window", "shape"], "star", "literal_error"),
        (["decoration", "archetype"], "collage", "literal_error"),
        (["decoration", "layers", 0, "kind"], "text", "union_tag_invalid"),
        (["decoration", "layers", 0, "shape"], "triangle", "union_tag_invalid"),
        (["decoration", "layers", 0, "distance"], 0.95, "spec_outside_frame"),
        (["decoration", "layers", 0, "thickness"], 0, "greater_than"),
        (["decoration", "layers", 0, "edge"], "left", "literal_error"),
        (["decoration", "layers", 0, "color"], "#fff", "string_pattern_mismatch"),
        (["decoration", "layers", 1, "width"], 0.2, "less_than_equal"),
        (["decoration", "layers", 1, "opacity"], 1.5, "less_than_equal"),
        (["decoration", "layers", 2, "box", "x"], 0.9, "spec_outside_frame"),
        (["decoration", "layers", 2, "rotate"], 270, "less_than_equal"),
        (["decoration", "layers", 3, "piece"], "../etc/passwd", "string_pattern_mismatch"),
        (["decoration", "layers", 3, "anchor"], "middle", "literal_error"),
        (["decoration", "layers", 3, "size"], 0, "greater_than"),
        (["decoration", "layers", 3, "mirror"], "both", "literal_error"),
        (["decoration", "layers", 3, "offset", "x"], 2, "less_than_equal"),
        (["decoration", "layers"], DELETE, "missing"),
        (["decoration", "layers"], [{"kind": "piece"}] * 65, "too_long"),
    ],
)
def test_invalid_specs_are_rejected_with_a_stable_code(
    path: list[str | int], value: Any, code: str
) -> None:
    assert code in {found for _, found in problems(with_change(path, value))}


def test_rounded_and_mask_windows_take_their_setting() -> None:
    rounded = with_change(["window", "shape"], "rounded")
    rounded["window"]["radius"] = 0.05
    assert read_spec(rounded).window.radius == 0.05
    rounded["window"]["radius"] = 0.6
    assert problems(rounded) == [(("window", "radius"), "less_than_equal")]

    mask = with_change(["window", "shape"], "mask")
    mask["window"]["mask"] = MASK
    assert read_spec(mask).window.mask == MASK


def test_a_spec_is_immutable() -> None:
    spec = read_spec(example())
    with pytest.raises(ValueError, match="frozen"):
        spec.decoration.archetype = "stroke"


def test_the_committed_json_schema_is_current() -> None:
    assert SCHEMA_FILE.read_text() == spec_schema.render(), (
        "The frame spec schema is out of date. Run "
        "'uv run framegen-spec-schema ../schemas/frame-spec.schema.json' and commit it."
    )


def test_the_json_schema_describes_the_spec() -> None:
    schema = json.loads(spec_schema.render())
    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["required"]) == {"specVersion", "aspect", "window", "decoration"}
    assert schema["additionalProperties"] is False
    assert "overlapsWindow" in schema["$defs"]["Piece"]["properties"]


def test_a_window_of_exactly_the_minimum_is_allowed() -> None:
    for top, bottom in [(0, 0.8), (0.1, 0.7), (0.4, 0.4)]:
        data = with_change(
            ["window", "portrait", "inset"], {"top": top, "bottom": bottom, "start": 0, "end": 0}
        )
        assert read_spec(data)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["decoration", "layers", 1, "opacity"], "0.5"),
        (["decoration", "layers", 1, "opacity"], True),
        (["decoration", "layers", 3, "overlapsWindow"], "yes"),
    ],
)
def test_values_are_not_coerced(path: list[str | int], value: Any) -> None:
    assert problems(with_change(path, value))


def test_problem_locations_are_paths_into_the_json() -> None:
    data = example()
    del data["decoration"]["layers"][2]["box"]["width"]
    data["decoration"]["layers"][3]["mirror"] = "both"
    found = problems(data)
    assert (("decoration", "layers", 2, "box", "width"), "missing") in found
    assert (("decoration", "layers", 3, "mirror"), "literal_error") in found
    mask = with_change(["window", "shape"], "mask")
    mask["window"]["mask"] = "ast_x"
    assert problems(mask) == [(("window", "mask"), "string_pattern_mismatch")]
    for location, _ in found:
        node: Any = data
        for step in location[:-1]:
            node = node[step]


def test_ids_have_the_real_format() -> None:
    for value in ["pc_bottle", "pc_" + "a" * 27, "pc_" + "A2" * 13, PIECE + "\n"]:
        assert problems(with_change(["decoration", "layers", 3, "piece"], value))
