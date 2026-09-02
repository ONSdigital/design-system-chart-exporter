"""Service name, version and build metadata, resolved once at import time."""

import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

_PYPROJECT_PATH: Final = Path(__file__).parents[1] / "pyproject.toml"

GIT_COMMIT: Final = os.environ.get("GIT_COMMIT", "")
GIT_TAG: Final = os.environ.get("GIT_TAG", "")

try:
    _PROJECT: Final = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]
    SERVICE_NAME = _PROJECT["name"]
    VERSION = GIT_TAG or GIT_COMMIT or _PROJECT["version"]
except OSError, KeyError, tomllib.TOMLDecodeError:  # pragma: no cover
    SERVICE_NAME = "design-system-chart-exporter"
    VERSION = "unknown"


def iso8601(timestamp: datetime) -> str:
    """Format a datetime as ISO 8601 UTC per the DP health check spec."""
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_build_time() -> str:
    """Convert the BUILD_TIME unix timestamp env var to an ISO 8601 string."""
    build_time = os.environ.get("BUILD_TIME")

    if not build_time:
        return ""
    try:
        return iso8601(datetime.fromtimestamp(int(build_time), tz=UTC))
    except ValueError, OverflowError, OSError:
        return ""


BUILD_TIME: Final = _read_build_time()
