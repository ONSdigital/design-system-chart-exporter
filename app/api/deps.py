"""Dependencies for the API layer: content-type guard and service providers."""

from typing import Any, Protocol

from fastapi import Request

from app.api.errors import RequestError
from app.domain.models import RenderedChart


class ChartExporter(Protocol):  # pylint: disable=too-few-public-methods
    """What the charts route needs from the service layer.

    A Protocol (structural typing): anything with a matching async ``export``
    method satisfies it — the real service in phase 5, stubs in tests — with
    no inheritance or imports required in either direction.
    """

    async def export(self, *, chart_config: dict[str, Any]) -> RenderedChart:
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


class _UnwiredExporter:  # pylint: disable=too-few-public-methods
    """Placeholder exporter that fails on use, not on dependency resolution.

    Dependencies resolve BEFORE the request body is validated, so the
    provider itself must stay cheap and side-effect free — raising here
    instead of in the provider keeps validation 400s working while the real
    service is not yet wired.
    """

    async def export(self, *, chart_config: dict[str, Any]) -> RenderedChart:
        raise NotImplementedError("chart exporter is not wired up yet (phase 5)")


def get_chart_exporter() -> ChartExporter:
    """Provide the chart exporter service.

    Returns the real service from phase 5 onwards; tests override this
    dependency with stubs via ``app.dependency_overrides[get_chart_exporter]``.
    """
    return _UnwiredExporter()
