"""ChartRenderer tests, in two tiers.

Fast tests exercise the semaphore/timeout control flow with a stubbed
_do_render (deterministic, no browser). Tests marked @pytest.mark.slow use a
real Chromium via Playwright and cover the browser-touching internals.
"""

import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import Error as PlaywrightError

from app.domain.exceptions import RendererBusy, RenderError, RenderTimeout
from app.services.png import read_png_dimensions
from app.services.renderer import ChartRenderer
from app.services.templating import render_chart_html
from tests.helpers import CHART_CONFIG


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
    release = asyncio.Event()
    entered = {"first": asyncio.Event(), "second": asyncio.Event()}
    running = []

    async def controlled_render(html):
        running.append(html)
        entered[html].set()
        await release.wait()
        return b"png-bytes"

    renderer._do_render = controlled_render

    first = asyncio.ensure_future(renderer.render("first"))
    await entered["first"].wait()  # first holds the only slot
    second = asyncio.ensure_future(renderer.render("second"))

    # The second render must NOT enter _do_render while the slot is held
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(entered["second"].wait(), timeout=0.2)
    assert running == ["first"]

    release.set()
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


@pytest.fixture()
def local_http_server():
    """A real HTTP listener on 127.0.0.1 that records every request it receives."""
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port, hits
    server.shutdown()


@pytest.mark.slow
async def test_render_context_cannot_reach_the_network(renderer, local_http_server):
    """SSRF mitigation: every request the page makes is aborted, whatever the initiator."""
    port, hits = local_http_server
    base = f"http://127.0.0.1:{port}"
    html = f"""<html><head><link rel="stylesheet" href="{base}/css"></head><body>
        <img src="{base}/img"><iframe src="{base}/frame"></iframe>
        <script>fetch("{base}/fetch"); new Image().src = "{base}/img2";</script>
        </body></html>"""

    await renderer.render(html)

    assert hits == []


@pytest.mark.slow
async def test_context_is_closed_after_a_successful_render(renderer):
    await renderer.render("<html><body>x</body></html>")

    assert renderer._browser.contexts == []


@pytest.mark.slow
async def test_context_is_closed_after_a_render_timeout(monkeypatch):
    """A timed-out render must not leak its context: that is the memory the semaphore protects."""
    renderer = make_renderer(render_timeout_seconds=0.5)
    await renderer.start()

    async def hang_forever(page):
        await asyncio.sleep(60)

    monkeypatch.setattr(renderer, "_wait_until_ready", hang_forever)
    try:
        with pytest.raises(RenderTimeout):
            await renderer.render("<html><body>x</body></html>")

        assert renderer._browser.contexts == []
        assert not renderer._sem.locked()
    finally:
        await renderer.stop()


@pytest.mark.slow
async def test_playwright_failures_become_render_error_and_close_the_context(renderer, monkeypatch):
    async def explode(page):
        raise PlaywrightError("boom")

    monkeypatch.setattr(renderer, "_wait_until_ready", explode)

    with pytest.raises(RenderError, match="browser render failed"):
        await renderer.render("<html><body>x</body></html>")

    assert renderer._browser.contexts == []


@pytest.mark.slow
async def test_concurrent_renders_on_a_dead_browser_relaunch_it_once(monkeypatch):
    """N requests hitting a crashed browser must trigger exactly one relaunch (the lock)."""
    renderer = make_renderer(max_concurrent_renders=5, queue_timeout_seconds=5.0)
    await renderer.start()
    try:
        await renderer._browser.close()  # simulate a crash
        browser_type = renderer._playwright.chromium
        original_launch = browser_type.launch
        launches = []

        async def counting_launch(**kwargs):
            launches.append(kwargs)
            return await original_launch(**kwargs)

        monkeypatch.setattr(browser_type, "launch", counting_launch)

        results = await asyncio.gather(*(renderer.render("<html><body>x</body></html>") for _ in range(5)))

        assert len(launches) == 1
        assert all(read_png_dimensions(png) == (800, 600) for png in results)
        assert renderer.is_ready is True
    finally:
        await renderer.stop()


@pytest.mark.slow
async def test_stop_closes_the_browser_and_is_idempotent():
    renderer = make_renderer()
    await renderer.start()
    browser = renderer._browser

    await renderer.stop()

    assert browser.is_connected() is False
    assert renderer.is_ready is False
    await renderer.stop()  # safe to call again (and on a never-started renderer)


@pytest.fixture()
def tcp_listener():
    """A raw TCP listener on 127.0.0.1 that records every inbound connection.

    A WebSocket handshake begins with a TCP connect; if the CSP/route block
    works, no connection is ever made, so the count stays zero.
    """
    connections = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept_loop():
        server.settimeout(0.25)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                connections.append(conn)
            except OSError:
                continue

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield port, connections
    stop.set()
    thread.join(timeout=1)
    server.close()


@pytest.mark.slow
async def test_render_context_cannot_open_a_websocket(renderer, tcp_listener):
    """SSRF defence in depth: caller markup cannot open a WebSocket out of the render context."""
    port, connections = tcp_listener
    html = f"""<html><body><script>
        try {{ new WebSocket("ws://127.0.0.1:{port}/probe"); }} catch (e) {{}}
        </script></body></html>"""

    await renderer.render(html)
    await asyncio.sleep(0.3)  # give any (blocked) connection attempt time to land

    assert connections == []
