"""Export the FastAPI OpenAPI schema to openapi.yaml at the repo root."""

import sys
from pathlib import Path

import yaml

from app.main import app

_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "openapi.yaml"


class IndentedListDumper(yaml.SafeDumper):
    """Custom YAML dumper to meet linter requirements for OpenAPI schema formatting."""

    best_indent = 2

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def render_schema() -> str:
    """Return the app's OpenAPI schema as a YAML string."""
    schema = app.openapi()
    return str(yaml.dump(schema, Dumper=IndentedListDumper, sort_keys=False))


def main() -> int:
    """Write or check openapi.yaml, depending on the --check flag."""
    rendered = render_schema()

    if "--check" in sys.argv[1:]:
        current = _OUTPUT_PATH.read_text(encoding="utf-8") if _OUTPUT_PATH.exists() else ""
        if current != rendered:
            print(f"{_OUTPUT_PATH.name} is out of date. Run 'make openapi' to regenerate it.", file=sys.stderr)
            return 1
        return 0

    _OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
