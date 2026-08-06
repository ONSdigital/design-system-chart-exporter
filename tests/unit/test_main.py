import re
from datetime import UTC, datetime
from http import HTTPStatus

from app.main import _BUILD_TIME, _GIT_COMMIT, _read_build_time


def test_health(client):
    """Test the health endpoint."""
    now = datetime.now(UTC)
    response = client.get("/health")

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "OK"
    assert body["checks"] == []
    assert body["version"]["version"] == "0.1.0"
    assert body["version"]["language"] == "python"
    assert body["version"]["git_commit"] == _GIT_COMMIT
    assert body["version"]["build_time"] == _BUILD_TIME

    # Timestamps use the ISO 8601 UTC format from the DP health check spec
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", body["start_time"])

    # Sense-check that the start_time is in the past and uptime is non-negative
    assert datetime.fromisoformat(body["start_time"]) <= now
    assert body["uptime"] >= 0


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
