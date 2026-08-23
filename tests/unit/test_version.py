from app.version import SERVICE_NAME, _read_build_time


def test_service_name_read_from_pyproject():
    """The service name comes from pyproject.toml."""
    assert SERVICE_NAME == "design-system-chart-exporter"


def test_read_build_time_set(monkeypatch):
    """A BUILD_TIME unix timestamp is converted to an ISO 8601 string."""
    monkeypatch.setenv("BUILD_TIME", "0")
    assert _read_build_time() == "1970-01-01T00:00:00.000Z"


def test_read_build_time_unset(monkeypatch):
    """An unset BUILD_TIME results in an empty string."""
    monkeypatch.delenv("BUILD_TIME", raising=False)
    assert _read_build_time() == ""


def test_read_build_time_invalid(monkeypatch):
    """A non-numeric BUILD_TIME results in an empty string."""
    monkeypatch.setenv("BUILD_TIME", "not-a-timestamp")
    assert _read_build_time() == ""
