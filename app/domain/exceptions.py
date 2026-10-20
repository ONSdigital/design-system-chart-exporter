"""Domain exceptions raised by services and storage.

Nothing here knows about HTTP: the mapping to status codes and client-facing
error documents lives in api/errors.py. Exception messages may contain
internal detail (they go to logs only) and must never reach a response body.
"""


class ChartExporterError(Exception):
    """Base class for all domain errors raised by this service."""


class RenderError(ChartExporterError):
    """Chart rendering failed (bad config, browser crash, non-PNG output)."""


class RenderTimeout(RenderError):
    """The render exceeded the configured render timeout."""


class RendererBusy(ChartExporterError):
    """No render slot became free within the configured queue timeout."""


class StorageError(ChartExporterError):
    """Uploading the rendered chart to object storage failed."""
