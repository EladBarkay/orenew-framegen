"""Writes the frame spec's JSON Schema, so clients and the planner can validate specs."""

import json
import sys
from pathlib import Path

from framegen.spec.frame import FrameSpec

SCHEMA_ID = "https://github.com/EladBarkay/orenew-framegen/schemas/frame-spec.schema.json"


def render() -> str:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **FrameSpec.model_json_schema(by_alias=True, mode="validation"),
    }
    schema["description"] = (
        f"{schema['description']} This schema checks each field. FrameGen also checks "
        "rules across fields that it cannot express: the window keeps at least 20% of the "
        "frame; bars, boxes, frame strokes and piece anchors stay inside the frame; "
        "portrait is not wider than tall; a radius only for 'rounded' and a mask only for "
        "'mask'; each decoration archetype has its layers; and the headline, date and "
        "stamp each have their own slot in each orientation ('under-headline' needs a "
        "headline); a Gregorian date pattern shows at least one date field, each run of "
        "a letter being a whole field (d, dd, M to MMMM, yy, yyyy), and a Gregorian "
        "format has a pattern or a style, not both; a date is in 1900-2199; text shows "
        "at least one visible character and has no control, direction-override or "
        "unpaired surrogate characters."
    )
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: framegen-spec-schema <output-file>")
    Path(sys.argv[1]).write_text(render())
