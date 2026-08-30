"""ChartRenderer tests, in two tiers.

Fast tests exercise the semaphore/timeout control flow with a stubbed
_do_render (deterministic, no browser). Tests marked @pytest.mark.slow use a
real Chromium via Playwright and cover the browser-touching internals.
"""

import asyncio

import pytest

from app.domain.exceptions import RendererBusy, RenderTimeout
from app.services.png import read_png_dimensions
from app.services.renderer import ChartRenderer
from app.services.templating import render_chart_html
from tests.unit.services.test_templating import CHART_CONFIG


def make_renderer(**overrides):
    params = {
        "viewport_width": 800,
        "viewport_height": 600,
        "device_scale_factor": 1.0,
        "max_concurrent_renders": 1,
        "render_timeout_seconds": 5.0,
        "queue_timeout_seconds": 0.2,
    }
    params.update(overrides)
    return ChartRenderer(**params)


# Fast tests: control flow with a stubbed _do_render
async def test_render_timeout_raises_and_releases_slot():
    renderer = make_renderer(render_timeout_seconds=0.05)

    async def never_finishes(html):
        await asyncio.sleep(60)

    renderer._do_render = never_finishes

    with pytest.raises(RenderTimeout):
        await renderer.render("<html></html>")

    # The slot must have been released in the finally block
    assert not renderer._sem.locked()


async def test_queue_timeout_raises_renderer_busy():
    renderer = make_renderer(queue_timeout_seconds=0.05)
    await renderer._sem.acquire()  # occupy the only slot

    try:
        with pytest.raises(RendererBusy):
            await renderer.render("<html></html>")
    finally:
        renderer._sem.release()


async def test_semaphore_bounds_concurrency():
    """With one slot, a second render must wait; it gets the slot on release."""
    renderer = make_renderer(queue_timeout_seconds=5.0)
    release_first = asyncio.Event()
    running = []

    async def controlled_render(html):
        running.append(html)
        await release_first.wait()
        return b"png-bytes"

    renderer._do_render = controlled_render

    first = asyncio.ensure_future(renderer.render("first"))
    await asyncio.sleep(0.05)

    second = asyncio.ensure_future(renderer.render("second"))
    await asyncio.sleep(0.05)

    # Only the first render entered _do_render; the second is queued
    assert running == ["first"]

    release_first.set()
    assert await first == b"png-bytes"
    assert await second == b"png-bytes"

    assert running == ["first", "second"]


async def test_is_ready_false_before_start():
    assert make_renderer().is_ready is False


# Slow tests: real Chromium
@pytest.fixture()
async def renderer():
    instance = make_renderer()
    await instance.start()
    yield instance
    await instance.stop()


@pytest.mark.slow
async def test_renders_page_to_png_at_viewport_size(renderer):
    png = await renderer.render("<html><body><h1>Hello</h1></body></html>")

    assert read_png_dimensions(png) == (800, 600)


@pytest.mark.slow
async def test_device_scale_factor_doubles_pixel_dimensions():
    renderer = make_renderer(device_scale_factor=2.0)
    await renderer.start()

    try:
        png = await renderer.render("<html><body>hi</body></html>")
        # PNG dimensions are physical pixels, not CSS pixels
        assert read_png_dimensions(png) == (1600, 1200)
    finally:
        await renderer.stop()


@pytest.mark.slow
async def test_chart_element_is_screenshotted_when_present(renderer):
    html = (
        '<html><body><div class="ons-chart" style="width: 300px; height: 200px; background: #eee"></div></body></html>'
    )

    png = await renderer.render(html)

    assert read_png_dimensions(png) == (300, 200)


@pytest.mark.slow
async def test_renders_real_design_system_chart(renderer):
    """End-to-end templating + browser: the DS chart renders with zero network."""
    html = render_chart_html(chart_config=CHART_CONFIG, language="en")

    png = await renderer.render(html)

    width, height = read_png_dimensions(png)
    # The chart element screenshot: what matters is that Highcharts drew
    # something plausible from purely inlined assets (no network)
    assert width > 200
    assert height > 200


@pytest.mark.slow
async def test_browser_crash_recovery(renderer):
    """A dead browser is relaunched on the next render, under the lock."""
    await renderer._browser.close()  # simulate a crash
    assert renderer.is_ready is False

    png = await renderer.render("<html><body>back</body></html>")

    assert read_png_dimensions(png) == (800, 600)
    assert renderer.is_ready is True
