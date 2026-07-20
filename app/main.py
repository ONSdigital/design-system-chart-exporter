import platform
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

_START_TIME: Final = datetime.now(UTC)
_PYPROJECT_PATH: Final = Path(__file__).parents[1] / "pyproject.toml"
_VERSION: Final = tomllib.loads(_PYPROJECT_PATH.read_text())["project"]["version"]

Status = Literal["OK", "WARNING", "CRITICAL"]


class VersionInfo(BaseModel):
    version: str
    git_commit: str
    build_time: str
    language: str
    language_version: str


class Check(BaseModel):
    name: str
    status: Status
    status_code: int | None = None
    message: str
    last_checked: str | None
    last_success: str | None
    last_failure: str | None


class HealthResponse(BaseModel):
    status: Status
    version: VersionInfo
    uptime: int
    start_time: str
    checks: list[Check]


@app.get("/health")
def health() -> HealthResponse:
    """Returns the service health status per the DP health check specification.

    See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md
    """
    now = datetime.now(UTC)
    return HealthResponse(
        status="OK",
        version=VersionInfo(
            version=_VERSION,
            git_commit="",
            build_time="",
            language="python",
            language_version=platform.python_version(),
        ),
        uptime=int((now - _START_TIME).total_seconds() * 1000),
        start_time=_START_TIME.isoformat(),
        checks=[],
    )
