"""Rewrite ``url("../fonts/...")`` references in a CSS file to data: URIs.

Used by load-design-system-templates.sh so the vendored stylesheet is fully
self-contained: the render context blocks ALL network access, and data: URIs
are the one way font bytes can reach it. Run as:

    python3 scripts/inline_css_fonts.py <css_in> <fonts_dir> <css_out>
"""

import base64
import re
import sys
from pathlib import Path

_MIME_TYPES = {".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf"}
_FONT_URL = re.compile(r'url\("\.\./fonts/([^"]+)"\)')


def inline_fonts(css: str, fonts_dir: Path) -> str:
    """Return the CSS with every ../fonts/ url() replaced by a data: URI."""

    def replace(match: re.Match[str]) -> str:
        font_path = fonts_dir / match.group(1)
        mime_type = _MIME_TYPES[font_path.suffix]
        encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f'url("data:{mime_type};base64,{encoded}")'

    return _FONT_URL.sub(replace, css)


def main() -> int:
    """CLI entrypoint: css_in, fonts_dir, css_out."""
    css_in, fonts_dir, css_out = (Path(arg) for arg in sys.argv[1:4])
    css_out.write_text(inline_fonts(css_in.read_text(encoding="utf-8"), fonts_dir), encoding="utf-8")
    remaining = _FONT_URL.findall(css_out.read_text(encoding="utf-8"))

    if remaining:
        print(f"ERROR: font references not inlined: {remaining}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
