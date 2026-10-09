"""Response models for the DP health check specification.

See: https://github.com/ONSdigital/dp-standards/blob/main/HEALTH_CHECK_SPECIFICATION.md
"""

from typing import Literal

from pydantic import BaseModel, Field

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
