import struct

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_chart_exporter
from app.config import get_settings
from app.main import app

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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

    def __init__(self, png=None, error=None, ready=True):
        self.png = png if png is not None else make_png_bytes()
        self.error = error
        self.is_ready = ready
        self.html_pages = []

    async def render(self, html):
        self.html_pages.append(html)
        if self.error is not None:
            raise self.error
        return self.png

    async def stop(self):
        """No-op: tests swap this onto app.state, and the lifespan stops it."""


@pytest.fixture()
def client(monkeypatch):
    """A test client with valid config and the lifespan running.

    Entering the TestClient context manager runs the app's lifespan, so the
    required environment must be in place first. The settings cache is
    cleared on both sides so no test observes another test's environment.
    """
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP", "false")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    """Reset dependency overrides after every test — the app object is shared."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def use_exporter():
    """Install a StubExporter via FastAPI's dependency override mechanism."""

    def _install(stub=None):
        stub = stub if stub is not None else StubExporter()
        app.dependency_overrides[get_chart_exporter] = lambda: stub
        return stub

    return _install
