"""Writes the API's OpenAPI document, so clients can be generated from it without a server."""

import json
import sys
from pathlib import Path

from framegen.api.app import create_app


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: framegen-openapi <output-file>")
    Path(sys.argv[1]).write_text(render())
