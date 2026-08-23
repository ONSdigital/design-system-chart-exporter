import re
from datetime import UTC, datetime
from http import HTTPStatus

from app.main import app
from app.version import BUILD_TIME, GIT_COMMIT
from tests.unit.conftest import StubRenderer

ISO_8601 = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"


def test_health_ok_when_browser_ready(client):
    """With a connected browser the service reports OK with a passing check."""
    app.state.renderer = StubRenderer(ready=True)
    now = datetime.now(UTC)

    response = client.get("/health")

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "OK"
    assert body["version"]["version"] == "0.1.0"
    assert body["version"]["language"] == "python"
    assert body["version"]["git_commit"] == GIT_COMMIT
    assert body["version"]["build_time"] == BUILD_TIME

    [check] = body["checks"]
    assert check["name"] == "browser"
    assert check["status"] == "OK"
    assert check["message"] == "chromium browser is connected"
    assert re.fullmatch(ISO_8601, check["last_checked"])
    assert check["last_success"] == check["last_checked"]
    assert check["last_failure"] is None

    # Timestamps use the ISO 8601 UTC format from the DP health check spec
    assert re.fullmatch(ISO_8601, body["start_time"])
    assert datetime.fromisoformat(body["start_time"]) <= now
    assert body["uptime"] >= 0


def test_health_critical_when_browser_down(client):
    """Readiness reflects browser.is_connected(): down -> CRITICAL + HTTP 500.

    The client fixture starts with launch_browser_on_startup=false, so the
    real renderer exists but has no connected browser.
    """
    response = client.get("/health")

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    body = response.json()
    assert body["status"] == "CRITICAL"
    [check] = body["checks"]
    assert check["name"] == "browser"
    assert check["status"] == "CRITICAL"
    assert check["message"] == "chromium browser is not connected"
    assert check["last_success"] is None
    assert re.fullmatch(ISO_8601, check["last_failure"])
