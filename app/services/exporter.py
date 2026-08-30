"""ChartExportService: the render-and-store orchestration behind POST /charts.

Flow (spec-mandated ordering): generate the UUID FIRST, derive the key
deterministically as ``{prefix}{id}.png``, render the config to HTML, render
the HTML to PNG in the browser, read the true pixel dimensions from the PNG
bytes, then upload. The upload goes through ``asyncio.to_thread`` because
boto3 is blocking and must never run directly on the event loop —
``to_thread`` (rather than starlette's run_in_threadpool) keeps this module
free of HTTP-framework imports per the dependency rule.

Durations are measured and logged from day one (render_ms, upload_ms), keyed
by chart id. chart_config itself is NEVER logged: charts may contain
sensitive pre-release data.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from app.domain.models import RenderedChart
from app.logging import get_logger
from app.services.png import read_png_dimensions
from app.services.templating import render_chart_html
from app.storage.base import StorageBackend

log = get_logger()

_PNG_CONTENT_TYPE = "image/png"


class SupportsRender(Protocol):  # pylint: disable=too-few-public-methods
    """The one renderer capability this service needs (satisfied by ChartRenderer)."""

    async def render(self, html: str) -> bytes:
        """Render an HTML page to PNG bytes."""


class ChartExportService:  # pylint: disable=too-few-public-methods
    """Renders a chart config and stores the PNG privately."""

    def __init__(self, *, renderer: SupportsRender, storage: StorageBackend, key_prefix: str) -> None:
        self._renderer = renderer
        self._storage = storage
        self._key_prefix = key_prefix

    async def export(self, *, chart_config: dict[str, Any], language: str) -> RenderedChart:
        """Render chart_config to a PNG, store it, and return the object metadata.

        Raises:
            RenderError: templating failed, the browser failed, or the
                screenshot is not a valid PNG.
            RenderTimeout: the render exceeded its timeout.
            RendererBusy: no render slot became free in time.
            StorageError: the upload failed.
        """
        chart_id = uuid4()
        created_at = datetime.now(UTC)
        key = f"{self._key_prefix}{chart_id}.png"

        html = render_chart_html(chart_config=chart_config, language=language)

        render_started = time.perf_counter()
        png = await self._renderer.render(html)
        render_ms = round((time.perf_counter() - render_started) * 1000)

        width, height = read_png_dimensions(png)

        upload_started = time.perf_counter()
        stored = await asyncio.to_thread(self._storage.put, key=key, data=png, content_type=_PNG_CONTENT_TYPE)
        upload_ms = round((time.perf_counter() - upload_started) * 1000)

        log.info(
            "chart exported",
            chart_id=str(chart_id),
            key=key,
            size_bytes=stored.size_bytes,
            width=width,
            height=height,
            render_ms=render_ms,
            upload_ms=upload_ms,
        )

        # bucket/content_type come from what storage actually persisted, so the
        # response reports the stored fact rather than re-deriving it from config.
        return RenderedChart(
            id=chart_id,
            bucket=stored.bucket,
            key=stored.key,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            width=width,
            height=height,
            created_at=created_at,
        )
