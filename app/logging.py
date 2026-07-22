"""Structlog configuration compliant with the DP logging standards.

See: https://github.com/ONSdigital/dp-standards/blob/main/LOGGING_STANDARDS.md
"""

import os
import sys
from typing import Final

import structlog

# Maps structlog method names to the DP logging standard severity codes.
_SEVERITY_LEVELS: Final[dict[str, int]] = {
    "critical": 0,
    "error": 1,
    "warning": 2,
    "info": 3,
    "debug": 3,  # Kept the same as info
}

env = os.environ.copy()
LOG_AS_JSON: Final[bool] = env.get("LOG_AS_JSON", str(not sys.stdout.isatty())).lower().strip() == "true"


def _add_severity(
    logger: structlog.types.WrappedLogger,  # pylint: disable=unused-argument
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Add a severity field to the event dict based on the method name."""
    event_dict["severity"] = _SEVERITY_LEVELS.get(method_name, 3)
    return event_dict


def _get_renderer() -> structlog.types.Processor:
    """Return the appropriate renderer based on the LOG_AS_JSON environment variable."""
    if LOG_AS_JSON:
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer()


def configure_logging(*, renderer: structlog.types.Processor | None = None) -> None:
    """Configure structlog to emit JSON lines matching the DP logging standard.

    Args:
        renderer: Optional structlog processor to use for rendering log output.
            If None, the renderer will be chosen based on the LOG_AS_JSON environment variable.
    """
    structlog.configure(
        processors=[
            _add_severity,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="created_at"),
            renderer or _get_renderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(namespace: str) -> structlog.types.FilteringBoundLogger:
    """Return a logger pre-bound with the service namespace."""
    logger: structlog.types.FilteringBoundLogger = structlog.get_logger().bind(namespace=namespace)
    return logger
