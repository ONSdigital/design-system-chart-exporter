"""GET /health endpoint following the DP health check specification.

See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md
"""

import platform
from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, Request

from app import version
from app.logging import get_logger
from app.schemas.health import HealthResponse, VersionInfo

router = APIRouter()
log = get_logger()

_VERSION_INFO: Final = VersionInfo(
    version=version.VERSION,
    git_commit=version.GIT_COMMIT,
    build_time=version.BUILD_TIME,
    language="python",
    language_version=platform.python_version(),
)


@router.get("/health")
def health(request: Request) -> HealthResponse:
    """Returns the service health status per the DP health check specification."""
    log.info("health check requested")
    now = datetime.now(UTC)
    start_time: datetime = request.app.state.start_time
    return HealthResponse(
        status="OK",
        version=_VERSION_INFO,
        uptime=int((now - start_time).total_seconds() * 1000),
        start_time=version.iso8601(start_time),
        checks=[],
    )
