import pytest
from pydantic import ValidationError

from app.schemas.health import Check, HealthResponse, VersionInfo

CHECK = Check(name="x", status="OK", message="m", last_checked=None, last_success=None, last_failure=None)
VERSION = VersionInfo(version="v", git_commit="", build_time="", language="python", language_version="3")


def test_health_response_allows_up_to_20_checks():
    """The DP health check specification caps the checks list at 20."""
    HealthResponse(status="OK", version=VERSION, uptime=0, start_time="t", checks=[CHECK] * 20)

    with pytest.raises(ValidationError):
        HealthResponse(status="OK", version=VERSION, uptime=0, start_time="t", checks=[CHECK] * 21)
