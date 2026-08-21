"""FastAPI application entrypoint."""

import os
import platform
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.logging import configure_logging, get_logger

app = FastAPI()

_START_TIME: Final = datetime.now(UTC)
_PYPROJECT_PATH: Final = Path(__file__).parents[1] / "pyproject.toml"
_GIT_COMMIT: Final = os.environ.get("GIT_COMMIT", "")
_GIT_TAG: Final = os.environ.get("GIT_TAG", "")


try:
    _PROJECT: Final = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]
    _SERVICE_NAME = _PROJECT["name"]
    _VERSION = _GIT_TAG or _GIT_COMMIT or _PROJECT["version"]
except OSError, KeyError, tomllib.TOMLDecodeError:  # pragma: no cover
    _SERVICE_NAME = "design-system-chart-exporter"
    _VERSION = "unknown"


def _iso8601(timestamp: datetime) -> str:
    """Format a datetime as ISO 8601 UTC per the DP health check spec."""
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_build_time() -> str:
    """Convert the BUILD_TIME unix timestamp env var to an ISO 8601 string."""
    build_time = os.environ.get("BUILD_TIME")
    if not build_time:
        return ""
    try:
        return _iso8601(datetime.fromtimestamp(int(build_time), tz=UTC))
    except ValueError, OverflowError, OSError:
        return ""


_BUILD_TIME: Final = _read_build_time()

configure_logging(namespace=_SERVICE_NAME)
log = get_logger()

Status = Literal["OK", "WARNING", "CRITICAL"]


class VersionInfo(BaseModel):
    """Version details for the running service."""

    version: str
    git_commit: str
    build_time: str
    language: str
    language_version: str


class Check(BaseModel):
    """Result of an individual health check."""

    name: str
    status: Status
    status_code: int | None = None
    message: str
    last_checked: str | None
    last_success: str | None
    last_failure: str | None


class HealthResponse(BaseModel):
    """Response body for the health check endpoint."""

    status: Status
    version: VersionInfo
    uptime: int
    start_time: str
    checks: list[Check] = Field(max_length=20)


@app.get("/health")
def health() -> HealthResponse:
    """Returns the service health status per the DP health check specification.
    See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md.
    """
    log.info("health check requested")
    now = datetime.now(UTC)
    return HealthResponse(
        status="OK",
        version=VersionInfo(
            version=_VERSION,
            git_commit=_GIT_COMMIT,
            build_time=_BUILD_TIME,
            language="python",
            language_version=platform.python_version(),
        ),
        uptime=int((now - _START_TIME).total_seconds() * 1000),
        start_time=_iso8601(_START_TIME),
        checks=[],
    )
