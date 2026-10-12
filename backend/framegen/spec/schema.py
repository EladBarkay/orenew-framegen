"""Writes the frame spec's JSON Schema, so clients and the planner can validate specs."""

import json
import sys
from pathlib import Path

from framegen.spec.models import FrameSpec

SCHEMA_ID = "https://github.com/EladBarkay/orenew-framegen/schemas/frame-spec.schema.json"


def render() -> str:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **FrameSpec.model_json_schema(by_alias=True, mode="validation"),
    }
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: framegen-spec-schema <output-file>")
    Path(sys.argv[1]).write_text(render())
