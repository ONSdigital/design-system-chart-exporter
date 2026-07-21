"""Structlog configuration compliant with the DP logging standards.

See: https://github.com/ONSdigital/dp-standards/blob/main/LOGGING_STANDARDS.md
"""

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


def _add_severity(
    logger: structlog.types.WrappedLogger,  # pylint: disable=unused-argument
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Add a severity field to the event dict based on the method name."""
    event_dict["severity"] = _SEVERITY_LEVELS.get(method_name, 3)
    return event_dict


def configure_logging() -> None:
    """Configure structlog to emit JSON lines matching the DP logging standard."""
    structlog.configure(
        processors=[
            _add_severity,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="created_at"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(namespace: str) -> structlog.types.FilteringBoundLogger:
    """Return a logger pre-bound with the service namespace."""
    logger: structlog.types.FilteringBoundLogger = structlog.get_logger().bind(namespace=namespace)
    return logger
