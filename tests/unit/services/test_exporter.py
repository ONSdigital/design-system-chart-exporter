"""ChartExportService tests: real orchestration over stub renderer + memory storage."""

import re
from datetime import UTC

import pytest

from app.domain.exceptions import RendererBusy, RenderError, StorageError
from app.services.exporter import ChartExportService
from app.storage.memory import MemoryStorageBackend
from tests.unit.conftest import StubRenderer, make_png_bytes
from tests.unit.services.test_templating import CHART_CONFIG

KEY_PATTERN = r"charts/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}\.png"


def make_service(renderer=None, storage=None, key_prefix="charts/"):
    return ChartExportService(
        renderer=renderer if renderer is not None else StubRenderer(),
        storage=storage if storage is not None else MemoryStorageBackend(),
        key_prefix=key_prefix,
    )


async def test_export_happy_path():
    renderer = StubRenderer(png=make_png_bytes(1200, 640))
    storage = MemoryStorageBackend(bucket="test-bucket")
    service = make_service(renderer, storage)

    chart = await service.export(chart_config=CHART_CONFIG, language="en")

    # UUID4 generated first; key derived deterministically from it
    assert chart.key == f"charts/{chart.id}.png"
    assert re.fullmatch(KEY_PATTERN, chart.key)
    # Dimensions come from the PNG bytes, size from their length
    assert (chart.width, chart.height) == (1200, 640)
    assert chart.size_bytes == len(renderer.png)
    assert chart.created_at.tzinfo == UTC
    # The PNG was uploaded under the derived key with the right content type
    stored = storage.objects[chart.key]
    assert stored.data == renderer.png
    assert stored.content_type == "image/png"


async def test_export_respects_key_prefix():
    service = make_service(key_prefix="other-prefix/")

    chart = await service.export(chart_config=CHART_CONFIG, language="en")

    assert chart.key == f"other-prefix/{chart.id}.png"


async def test_export_renders_templated_html():
    renderer = StubRenderer()
    service = make_service(renderer)

    await service.export(chart_config=CHART_CONFIG, language="en")

    [html] = renderer.html_pages
    assert '<html lang="en">' in html
    assert "data-highcharts-base-chart" in html


async def test_renderer_errors_propagate_and_nothing_is_stored():
    storage = MemoryStorageBackend()
    service = make_service(StubRenderer(error=RendererBusy("saturated")), storage)

    with pytest.raises(RendererBusy):
        await service.export(chart_config=CHART_CONFIG, language="en")

    assert storage.objects == {}


async def test_invalid_png_from_renderer_raises_render_error():
    service = make_service(StubRenderer(png=b"not-a-png"))

    with pytest.raises(RenderError, match="bad signature"):
        await service.export(chart_config=CHART_CONFIG, language="en")


async def test_storage_errors_propagate():
    storage = MemoryStorageBackend(fail_with=StorageError("bucket on fire"))
    service = make_service(storage=storage)

    with pytest.raises(StorageError, match="bucket on fire"):
        await service.export(chart_config=CHART_CONFIG, language="en")
