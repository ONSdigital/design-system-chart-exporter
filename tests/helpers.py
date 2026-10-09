"""Shared test doubles and fixtures-as-data, importable from any test module.

Kept out of conftest.py: conftest is loaded by pytest's own mechanism and
importing it as a module is fragile; a plain helpers module is not.
"""

import asyncio
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A representative Design System chart config (the shape Wagtail sends)
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


def make_png_bytes(width=1200, height=640):
    """Build the first 29 bytes of a PNG (signature + IHDR): enough for dimension parsing."""
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return PNG_SIGNATURE + b"\x00\x00\x00\r" + b"IHDR" + ihdr


class StubExporter:
    """Test double satisfying the ChartExporter protocol structurally."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def export(self, *, chart_config, language):
        self.calls.append((chart_config, language))
        if self.error is not None:
            raise self.error

        return self.result


class StubRenderer:
    """Test double satisfying the SupportsRender protocol: canned PNG or an error."""

    def __init__(self, png=None, error=None, ready=True, delay=0.0):
        self.png = png if png is not None else make_png_bytes()
        self.error = error
        self.delay = delay
        self.is_ready = ready
        self.html_pages = []
        self.stopped = False

    async def render(self, html):
        self.html_pages.append(html)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error

        return self.png

    async def stop(self):
        """Record the call: tests swap this onto app.state, and the lifespan stops it."""
        self.stopped = True


def run_python(code, env):
    """Run a snippet in a fresh interpreter with a controlled environment; return its stdout.

    For values resolved at import time (LOG_AS_JSON, LOG_LEVEL, VERSION), which
    cannot be re-read in-process without reloading modules that other modules
    hold references to.
    """
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith(("LOG_", "GIT_", "BUILD_TIME"))}
    result = subprocess.run(  # noqa: S603 - fixed interpreter, code is ours
        [sys.executable, "-c", code],
        env={**clean_env, **env},
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return result.stdout.strip()


def require_floci(host="localhost", port=4566):
    """Skip an e2e test when Floci is unreachable — but fail hard under CI.

    Locally, a developer who has not run `make up-deps` gets a clear skip.
    In CI (`CI` env var set by GitHub Actions) a missing emulator is a real
    failure, so the e2e layer can never silently pass by being skipped.
    """
    import pytest  # noqa: PLC0415 - test-only dependency, imported lazily

    try:
        with socket.create_connection((host, port), timeout=1):
            return
    except OSError:
        message = f"Floci is not reachable on {host}:{port} — start it with `make up-deps`"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
