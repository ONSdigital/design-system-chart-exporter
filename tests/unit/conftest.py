import json
import logging
import sys
from contextlib import contextmanager

import pytest
import structlog
from fastapi.testclient import TestClient

from app.api.deps import get_chart_exporter
from app.config import get_settings
from app.logging import configure_logging
from app.main import app
from app.version import SERVICE_NAME
from tests.helpers import StubExporter


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


@pytest.fixture()
def client_factory(monkeypatch):
    """Return a context manager building a TestClient with extra CHART_EXPORTER_* settings.

    Usage: ``with client_factory(max_body_bytes=64) as client: ...``
    """

    @contextmanager
    def _make(**settings):
        monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
        monkeypatch.setenv("CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP", "false")
        for name, value in settings.items():
            monkeypatch.setenv(f"CHART_EXPORTER_{name.upper()}", str(value))
        get_settings.cache_clear()

        with TestClient(app) as test_client:
            yield test_client
        get_settings.cache_clear()

    return _make


class _CurrentStdout:
    """A stream that resolves sys.stdout on every write."""

    def write(self, text):
        return sys.stdout.write(text)

    def flush(self):
        return sys.stdout.flush()


@pytest.fixture()
def json_logs(capsys):
    """Re-bind the log handler to this test's captured stdout and return a reader.

    The reader returns (raw_output, parsed_json_events). Needed because the
    handler installed at import time points at the original stdout, which
    pytest's capture has since replaced.
    """
    configure_logging(namespace=SERVICE_NAME, renderer=structlog.processors.JSONRenderer())
    # pytest closes and recreates the capsys stream between the setup and call
    # phases, so bind the handler to "whatever sys.stdout is right now" instead
    logging.getLogger().handlers[0].setStream(_CurrentStdout())

    def _read():
        raw = capsys.readouterr().out
        events = [json.loads(line) for line in raw.splitlines() if line.startswith("{")]
        return raw, events

    return _read
