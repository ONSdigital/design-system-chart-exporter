import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


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
