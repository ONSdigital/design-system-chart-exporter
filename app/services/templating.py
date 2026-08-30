"""Jinja templating: renders a chart config into a self-contained HTML page.

The rendered page inlines the vendored CSS and JS (see
scripts/load-design-system-templates.sh) because the render context blocks
all network access.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, TemplateError, select_autoescape
from jinja2.filters import do_tojson
from jinja2.runtime import Undefined
from jinja2.utils import pass_eval_context
from markupsafe import Markup

from app.domain.exceptions import RenderError

TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
_CHART_TEMPLATE = "chart.html"


def extend(value: list[Any], element: Any) -> None:
    """Append an item to a list, for use inside Design System macros.

    This could be achieved in Nunjucks with array.concat(item), and in Jinja2
    with array.append(item), but not with any syntax that is available in
    both, so the Design System templates expect this global:

        {% set _ = extend(series, seriesItem) %}
    """
    if not isinstance(value, list):
        # Likely called from a template macro, so we can't rely on
        # annotations and tooling for type safety.
        raise TypeError("First argument must be a list.")

    return value.append(element)


def _clean_undefined(value: Any) -> Any:
    """Recursively replace Jinja Undefined values with None for JSON dumping."""
    if isinstance(value, Undefined):
        return None
    if isinstance(value, dict):
        return {key: _clean_undefined(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_undefined(item) for item in value]
    return value


@pass_eval_context
def _safe_tojson(eval_ctx: Any, value: Any, indent: int | None = None) -> Markup:
    """Undefined-cleaning tojson that wraps AROUND Jinja's correct escaping.

    The Design System macros build config dicts whose optional entries are
    Jinja Undefined; plain json.dumps chokes on those. Cleaning first and
    then delegating to Jinja's own filter keeps the script-context escaping
    guarantees (spike lesson: never replace them with a naive json.dumps).
    """
    return do_tojson(eval_ctx, _clean_undefined(value), indent=indent)


@lru_cache
def _environment() -> Environment:
    """Build the Jinja environment once per process.

    The vendored CSS/JS are attached as Markup globals so chart.html can
    inline them without autoescaping mangling their content.
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=("html", "xml", "njk")),
        # chart_config is opaque: macros probe optional nested fields (e.g.
        # params.download.title), which must stay undefined-and-falsy rather
        # than raise, as Nunjucks would behave
        undefined=ChainableUndefined,
    )
    env.globals["extend"] = extend
    env.globals["undefined"] = None
    env.filters["tojson"] = _safe_tojson
    # Markup is safe here: these are our build-time vendored files, never
    # user input (S704 guards against wrapping untrusted strings)
    assets_dir = TEMPLATES_DIR / "assets"
    env.globals["design_system_css"] = Markup((assets_dir / "main.css").read_text(encoding="utf-8"))  # noqa: S704
    env.globals["design_system_js"] = Markup((assets_dir / "main.js").read_text(encoding="utf-8"))  # noqa: S704

    return env


def render_chart_html(*, chart_config: dict[str, Any], language: str) -> str:
    """Render the chart page HTML for the given (opaque) chart config.

    Raises:
        RenderError: if the templates are missing (design-system assets not
            vendored) or the config breaks template rendering.
    """
    try:
        return _environment().get_template(_CHART_TEMPLATE).render(chart_config=chart_config, language=language)
    except (TemplateError, TypeError, OSError) as exc:
        raise RenderError(f"chart template rendering failed: {exc}") from exc
