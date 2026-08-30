"""GET /health endpoint following the DP health check specification.

See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md
"""

import platform
from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, Request, Response

from app import version
from app.api.deps import get_renderer
from app.schemas.health import Check, HealthResponse, Status, VersionInfo

router = APIRouter()

_VERSION_INFO: Final = VersionInfo(
    version=version.VERSION,
    git_commit=version.GIT_COMMIT,
    build_time=version.BUILD_TIME,
    language="python",
    language_version=platform.python_version(),
)

# DP health check spec status -> HTTP status. WARNING has no producer yet (no
# check can currently be degraded-but-serving), but the mapping is defined so
# that adding such a check later is a one-line change here, not a missed case.
_HTTP_STATUS: Final[dict[Status, int]] = {"OK": 200, "WARNING": 429, "CRITICAL": 500}

# Severity order for aggregating individual checks into the overall status.
_SEVERITY: Final[dict[Status, int]] = {"OK": 0, "WARNING": 1, "CRITICAL": 2}


class CheckHistory:
    """Retains the last success/failure timestamp per named check across requests.

    A single health poll is a point-in-time reading; without retention, during
    an outage ``last_success`` would be null rather than "when it last worked".
    One instance lives on ``app.state`` for the process lifetime (created in the
    lifespan), so the timestamps survive between requests.
    """

    def __init__(self) -> None:
        self._last_success: dict[str, str] = {}
        self._last_failure: dict[str, str] = {}

    def record(self, name: str, *, ok: bool, timestamp: str) -> None:
        """Record the outcome of one check at ``timestamp``."""
        if ok:
            self._last_success[name] = timestamp
        else:
            self._last_failure[name] = timestamp

    def last_success(self, name: str) -> str | None:
        """Return the last time ``name`` was OK, or None if never."""
        return self._last_success.get(name)

    def last_failure(self, name: str) -> str | None:
        """Return the last time ``name`` failed, or None if never."""
        return self._last_failure.get(name)


def aggregate_status(checks: list[Check]) -> Status:
    """Return the overall status: the most severe of the individual checks."""
    if not checks:
        return "OK"
    return max((check.status for check in checks), key=lambda status: _SEVERITY[status])


def _browser_check(request: Request, now: datetime) -> Check:
    """Readiness of the shared browser: reflects browser.is_connected()."""
    ready = get_renderer(request).is_ready
    timestamp = version.iso8601(now)
    history: CheckHistory = request.app.state.check_history
    history.record("browser", ok=ready, timestamp=timestamp)

    return Check(
        name="browser",
        status="OK" if ready else "CRITICAL",
        message="chromium browser is connected" if ready else "chromium browser is not connected",
        last_checked=timestamp,
        last_success=history.last_success("browser"),
        last_failure=history.last_failure("browser"),
    )


@router.get(
    "/health",
    responses={
        429: {"model": HealthResponse, "description": "Service is degraded"},
        500: {"model": HealthResponse, "description": "Service is unhealthy"},
    },
)
def health(request: Request, response: Response) -> HealthResponse:
    """Returns the service health status per the DP health check specification.

    A dead browser makes the service CRITICAL (it cannot render), reported
    with HTTP 500 so orchestrators stop routing traffic to this instance.
    A degraded-but-serving check would be WARNING -> HTTP 429.
    """
    now = datetime.now(UTC)
    start_time: datetime = request.app.state.start_time
    checks = [_browser_check(request, now)]
    status = aggregate_status(checks)
    response.status_code = _HTTP_STATUS[status]

    return HealthResponse(
        status=status,
        version=_VERSION_INFO,
        uptime=int((now - start_time).total_seconds() * 1000),
        start_time=version.iso8601(start_time),
        checks=checks,
    )
