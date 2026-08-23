from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import app


def test_lifespan_stores_settings_and_start_time(client):
    """Startup loads validated settings and records the start time on app.state."""
    assert app.state.settings.s3_bucket == "test-bucket"
    assert isinstance(app.state.start_time, datetime)
    assert app.state.start_time.tzinfo == UTC


def test_boot_fails_loudly_without_s3_bucket(monkeypatch):
    """A missing CHART_EXPORTER_S3_BUCKET must crash startup, not 500 later."""
    monkeypatch.delenv("CHART_EXPORTER_S3_BUCKET", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="s3_bucket"), TestClient(app):
        pass  # pragma: no cover - startup fails before the body runs

    get_settings.cache_clear()
