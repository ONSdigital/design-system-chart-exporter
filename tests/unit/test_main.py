from datetime import UTC, datetime
from http import HTTPStatus


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

    # Sense-check that the start_time is in the past and uptime is positive
    assert datetime.fromisoformat(body["start_time"]) <= now
    assert body["uptime"] > 0
