"""Dependencies for the API layer: content-type guard and service providers."""

from typing import Any, Protocol

from fastapi import Request

from app.api.errors import RequestError
from app.domain.models import RenderedChart
from app.services.exporter import ChartExportService


class ChartExporter(Protocol):  # pylint: disable=too-few-public-methods
    """What the charts route needs from the service layer.

    A Protocol (structural typing): anything with a matching async ``export``
    method satisfies it — the real ChartExportService, stubs in tests — with
    no inheritance or imports required in either direction.
    """

    async def export(self, *, chart_config: dict[str, Any], language: str) -> RenderedChart:
        """Render chart_config to a PNG, store it, and return the object metadata."""


async def require_json_content_type(request: Request) -> None:
    """Reject a non-JSON Content-Type with 415 before the body is parsed.

    Runs as a router-level dependency, which FastAPI resolves before the
    endpoint's body parameter — so a bad Content-Type short-circuits without
    ever reading or validating the payload.
    """
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()

    if media_type != "application/json":
        raise RequestError(415, "unsupported_media_type", "Content-Type must be application/json.")


def get_chart_exporter(request: Request) -> ChartExporter:
    """Provide the chart exporter, wired to the process-wide renderer/storage.

    The renderer and storage live on app.state (created once in the
    lifespan); this provider assembles a thin service object per request.
    Providers must stay cheap and side-effect free: FastAPI resolves them
    BEFORE the request body is validated. Tests either override this
    dependency or swap app.state.renderer / app.state.storage.
    """
    state = request.app.state

    return ChartExportService(renderer=state.renderer, storage=state.storage, key_prefix=state.settings.s3_key_prefix)
