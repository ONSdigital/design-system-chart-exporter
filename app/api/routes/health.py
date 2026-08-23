"""GET /health endpoint following the DP health check specification.

See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md
"""

import platform
from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, Request, Response

from app import version
from app.logging import get_logger
from app.schemas.health import Check, HealthResponse, VersionInfo

router = APIRouter()
log = get_logger()

_VERSION_INFO: Final = VersionInfo(
    version=version.VERSION,
    git_commit=version.GIT_COMMIT,
    build_time=version.BUILD_TIME,
    language="python",
    language_version=platform.python_version(),
)


def _browser_check(request: Request, now: datetime) -> Check:
    """Readiness of the shared browser: reflects browser.is_connected()."""
    ready = request.app.state.renderer.is_ready
    timestamp = version.iso8601(now)
    return Check(
        name="browser",
        status="OK" if ready else "CRITICAL",
        message="chromium browser is connected" if ready else "chromium browser is not connected",
        last_checked=timestamp,
        last_success=timestamp if ready else None,
        last_failure=None if ready else timestamp,
    )


@router.get("/health", responses={500: {"model": HealthResponse, "description": "Service is unhealthy"}})
def health(request: Request, response: Response) -> HealthResponse:
    """Returns the service health status per the DP health check specification.

    A dead browser makes the service CRITICAL (it cannot render), reported
    with HTTP 500 so orchestrators stop routing traffic to this instance.
    """
    log.info("health check requested")
    now = datetime.now(UTC)
    start_time: datetime = request.app.state.start_time
    checks = [_browser_check(request, now)]
    healthy = all(check.status == "OK" for check in checks)
    if not healthy:
        response.status_code = 500
    return HealthResponse(
        status="OK" if healthy else "CRITICAL",
        version=_VERSION_INFO,
        uptime=int((now - start_time).total_seconds() * 1000),
        start_time=version.iso8601(start_time),
        checks=checks,
    )
