import re
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest

from app.api.routes.health import _HTTP_STATUS, aggregate_status
from app.main import app
from app.schemas.health import Check
from app.version import BUILD_TIME, GIT_COMMIT, VERSION
from tests.helpers import StubRenderer

ISO_8601 = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z"


def test_health_ok_when_browser_ready(client):
    """With a connected browser the service reports OK with a passing check."""
    app.state.renderer = StubRenderer(ready=True)
    now = datetime.now(UTC)

    response = client.get("/health")

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["status"] == "OK"
    assert body["version"]["version"] == VERSION
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


def test_uptime_is_reported_in_milliseconds(client):
    app.state.renderer = StubRenderer(ready=True)
    app.state.start_time = datetime.now(UTC) - timedelta(seconds=2)

    body = client.get("/health").json()

    assert 2000 <= body["uptime"] < 60_000


def test_health_needs_no_body_and_ignores_content_type(client):
    """GET /health is on a different router: the JSON content-type guard must not apply."""
    app.state.renderer = StubRenderer(ready=True)

    response = client.get("/health", headers={"content-type": "text/plain"})

    assert response.status_code == HTTPStatus.OK


def test_last_success_is_retained_across_a_later_failure(client):
    """During an outage, last_success shows when it last worked, not null."""
    app.state.renderer = StubRenderer(ready=True)
    first = client.get("/health").json()["checks"][0]
    assert first["last_success"] is not None

    app.state.renderer = StubRenderer(ready=False)
    second = client.get("/health").json()["checks"][0]

    assert second["status"] == "CRITICAL"
    assert second["last_success"] == first["last_success"]  # retained
    assert second["last_failure"] is not None


def test_last_failure_is_retained_after_recovery(client):
    """After recovery, last_failure still shows when it last broke."""
    app.state.renderer = StubRenderer(ready=False)
    down = client.get("/health").json()["checks"][0]

    app.state.renderer = StubRenderer(ready=True)
    up = client.get("/health").json()["checks"][0]

    assert up["status"] == "OK"
    assert up["last_failure"] == down["last_failure"]  # retained


def test_status_to_http_mapping():
    """DP spec status -> HTTP: OK 200, WARNING 429, CRITICAL 500."""
    assert _HTTP_STATUS == {"OK": 200, "WARNING": 429, "CRITICAL": 500}


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "OK"),
        (["OK"], "OK"),
        (["OK", "WARNING"], "WARNING"),
        (["OK", "WARNING", "CRITICAL"], "CRITICAL"),
        (["WARNING", "CRITICAL"], "CRITICAL"),
    ],
)
def test_aggregate_status_is_the_most_severe(statuses, expected):
    """Overall status is the most severe check; a WARNING degrades, a CRITICAL fails."""
    checks = [
        Check(name=str(i), status=s, message="", last_checked=None, last_success=None, last_failure=None)
        for i, s in enumerate(statuses)
    ]

    assert aggregate_status(checks) == expected
