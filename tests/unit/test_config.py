import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clean_settings_cache():
    """Ensure each test reads the environment fresh and leaves no cached state."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_s3_bucket_raises(monkeypatch):
    """s3_bucket is required; a missing env var is a hard validation error."""
    monkeypatch.delenv("CHART_EXPORTER_S3_BUCKET", raising=False)

    with pytest.raises(ValidationError, match="s3_bucket"):
        Settings()


def test_defaults(monkeypatch):
    """Only the bucket is required; everything else has a documented default."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")

    settings = Settings()

    assert settings.s3_bucket == "test-bucket"
    assert settings.s3_endpoint_url is None
    assert settings.s3_region is None
    assert settings.s3_key_prefix == "charts/"
    assert settings.s3_set_private_acl is True
    assert settings.viewport_width == 1200
    assert settings.viewport_height == 640
    assert settings.device_scale_factor == 1.0
    assert settings.max_concurrent_renders == 4
    assert settings.render_timeout_seconds == 15.0
    assert settings.queue_timeout_seconds == 5.0
    assert settings.max_body_bytes == 1_048_576


def test_env_overrides(monkeypatch):
    """Values are read from CHART_EXPORTER_-prefixed environment variables."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "other-bucket")
    monkeypatch.setenv("CHART_EXPORTER_S3_ENDPOINT_URL", "http://floci:4566")
    monkeypatch.setenv("CHART_EXPORTER_MAX_CONCURRENT_RENDERS", "8")
    monkeypatch.setenv("CHART_EXPORTER_S3_SET_PRIVATE_ACL", "false")

    settings = Settings()

    assert settings.s3_bucket == "other-bucket"
    assert settings.s3_endpoint_url == "http://floci:4566"
    assert settings.max_concurrent_renders == 8
    assert settings.s3_set_private_acl is False


def test_non_positive_limits_rejected(monkeypatch):
    """Zero or negative limits are configuration errors, caught at boot."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("CHART_EXPORTER_MAX_CONCURRENT_RENDERS", "0")

    with pytest.raises(ValidationError, match="max_concurrent_renders"):
        Settings()


def test_get_settings_is_cached(monkeypatch):
    """get_settings reads the environment once per process."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    first = get_settings()

    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "changed-bucket")
    second = get_settings()

    assert first is second
    assert second.s3_bucket == "test-bucket"
