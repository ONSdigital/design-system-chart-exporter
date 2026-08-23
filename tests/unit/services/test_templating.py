"""Templating tests. Require the vendored DS templates (make design-system)."""

import json
import re

import pytest

from app.domain.exceptions import RenderError
from app.services.templating import extend, render_chart_html

CHART_CONFIG = {
    "chartType": "column",
    "title": "Monthly Sales Revenue",
    "subtitle": "Revenue in thousands",
    "id": "sales-chart-001",
    "theme": "primary",
    "legend": False,
    "series": [{"data": [45.5, 52.3, 48.7], "name": "Sales"}],
    "xAxis": {"categories": ["Jan", "Feb", "Mar"], "title": "Month", "type": "linear"},
    "yAxis": {"title": "Revenue"},
}


def extract_config_json(html):
    """Pull the embedded Highcharts config JSON back out of the page."""
    match = re.search(r'<script type="application/json" data-highcharts-config--[^>]*>\s*(.*?)\s*</script>', html, re.S)
    assert match, "config script tag not found"
    return match.group(1)


def test_renders_chart_page():
    html = render_chart_html(chart_config=CHART_CONFIG, language="en")

    assert '<html lang="en">' in html
    assert "data-highcharts-base-chart" in html
    assert 'data-highcharts-type="column"' in html
    # Vendored assets are inlined; fonts are data: URIs, nothing external
    assert "font/woff2;base64" in html
    config = json.loads(extract_config_json(html))
    assert config["series"][0]["data"] == [45.5, 52.3, 48.7]
    assert config["chart"]["type"] == "column"


def test_undefined_config_entries_serialise_as_null():
    """Optional macro entries are Jinja Undefined; they must become JSON null."""
    html = render_chart_html(chart_config=CHART_CONFIG, language="en")

    config = json.loads(extract_config_json(html))
    # labelFormat was not supplied, so the macro passed an Undefined through
    assert config["yAxis"]["labels"]["format"] is None


def test_script_content_cannot_break_out_of_json_script_tag():
    """Spike lesson 5: '</script>' in a config string must not terminate the tag."""
    malicious = {**CHART_CONFIG, "series": [{"data": [1], "name": '</script><script>alert("pwned")</script>'}]}

    html = render_chart_html(chart_config=malicious, language="en")

    assert '</script><script>alert("pwned")' not in html
    config = json.loads(extract_config_json(html))
    # The payload survives as DATA, escaped as unicode sequences in the raw page
    assert config["series"][0]["name"] == '</script><script>alert("pwned")</script>'
    assert "\\u003c/script" in extract_config_json(html)


def test_paragraph_separator_is_escaped():
    """U+2028/U+2029 are legal JSON but illegal in old JS strings; must be escaped."""
    tricky = {**CHART_CONFIG, "series": [{"data": [1], "name": "line one\u2028line two"}]}

    html = render_chart_html(chart_config=tricky, language="en")

    raw_config = extract_config_json(html)
    assert "\u2028" not in raw_config
    assert "\\u2028" in raw_config


def test_html_context_is_autoescaped():
    """Titles are rendered into HTML by the .njk macro and must be escaped there."""
    sneaky = {**CHART_CONFIG, "title": '<img src=x onerror="alert(1)">'}

    html = render_chart_html(chart_config=sneaky, language="en")

    assert '<img src=x onerror="alert(1)">' not in html
    assert "&lt;img src=x onerror=" in html


def test_broken_config_raises_render_error():
    """A config that breaks template rendering maps to the domain RenderError."""
    with pytest.raises(RenderError, match="chart template rendering failed"):
        render_chart_html(chart_config={**CHART_CONFIG, "series": 42}, language="en")


def test_extend_appends_in_place():
    items = [1]
    assert extend(items, 2) is None
    assert items == [1, 2]


def test_extend_rejects_non_list():
    with pytest.raises(TypeError, match="must be a list"):
        extend("not-a-list", 2)
