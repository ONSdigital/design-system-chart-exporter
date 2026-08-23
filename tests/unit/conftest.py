import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_chart_exporter
from app.config import get_settings
from app.main import app


class StubExporter:
    """Test double satisfying the ChartExporter protocol structurally."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def export(self, *, chart_config):
        self.calls.append(chart_config)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture()
def client(monkeypatch):
    """A test client with valid config and the lifespan running.

    Entering the TestClient context manager runs the app's lifespan, so the
    required environment must be in place first. The settings cache is
    cleared on both sides so no test observes another test's environment.
    """
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
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
