import re
from datetime import UTC, datetime
from http import HTTPStatus

from app.version import BUILD_TIME, GIT_COMMIT


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
    assert body["version"]["git_commit"] == GIT_COMMIT
    assert body["version"]["build_time"] == BUILD_TIME

    # Timestamps use the ISO 8601 UTC format from the DP health check spec
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", body["start_time"])

    # Sense-check that the start_time is in the past and uptime is non-negative
    assert datetime.fromisoformat(body["start_time"]) <= now
    assert body["uptime"] >= 0
