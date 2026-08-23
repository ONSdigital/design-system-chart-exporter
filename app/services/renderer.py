"""ChartRenderer: browser lifecycle, per-request contexts, semaphore, timeouts.

Locked-in concurrency model:

- async_playwright exclusively; ONE browser per process (launched from the
  FastAPI lifespan), one cheap isolated browser CONTEXT per request.
- An asyncio.Semaphore bounds concurrent render contexts — a memory ceiling
  (each open context with a rendered chart is ~50-100MB), not a CPU one.
- Two mandatory timeouts: a bounded wait to ACQUIRE a slot (RendererBusy ->
  503, prevents unbounded queueing) and a bound on the render itself
  (RenderTimeout -> 500, prevents a pathological config pinning a slot
  forever while liveness still passes).
- Crash recovery: the browser is relaunched under an asyncio.Lock so
  concurrent requests don't spawn N browsers.
- ALL network access from the render context is blocked (SSRF mitigation);
  the page HTML is fully self-contained.

Browser-touching internals are excluded from fast-suite coverage
(pragma: no cover) and exercised by the @pytest.mark.slow tests instead.
"""

import asyncio

from playwright.async_api import Browser, Page, Playwright, Route, async_playwright
from playwright.async_api import Error as PlaywrightError

from app.domain.exceptions import RendererBusy, RenderError, RenderTimeout
from app.logging import get_logger

CHART_LOCATOR = ".ons-chart, .chart, [data-chart]"

log = get_logger()


class ChartRenderer:  # pylint: disable=too-many-instance-attributes
    """Renders self-contained HTML pages to PNG bytes with one shared browser."""

    # Deliberately takes each setting explicitly (not a Settings object) so
    # the service layer stays decoupled from app config and easy to test
    def __init__(  # noqa: PLR0913 # pylint: disable=too-many-arguments
        self,
        *,
        viewport_width: int,
        viewport_height: int,
        device_scale_factor: float,
        max_concurrent_renders: int,
        render_timeout_seconds: float,
        queue_timeout_seconds: float,
    ) -> None:
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        self._device_scale_factor = device_scale_factor
        self._render_timeout = render_timeout_seconds
        self._queue_timeout = queue_timeout_seconds
        self._sem = asyncio.Semaphore(max_concurrent_renders)
        self._relaunch_lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def is_ready(self) -> bool:
        """Whether a connected browser is available (drives readiness)."""
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> None:  # pragma: no cover - exercised by slow tests
        """Start the Playwright driver and launch the shared browser."""
        await self._ensure_browser()
        log.info("browser launched")

    async def stop(self) -> None:  # pragma: no cover - exercised by slow tests
        """Close the browser and stop the Playwright driver. Safe if never started."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        log.info("browser stopped")

    async def render(self, html: str) -> bytes:
        """Render HTML to PNG bytes, bounded by the semaphore and both timeouts.

        Raises:
            RendererBusy: no render slot became free within the queue timeout.
            RenderTimeout: the render itself exceeded the render timeout.
            RenderError: the browser failed to produce a screenshot.
        """
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._queue_timeout)
        except TimeoutError:
            raise RendererBusy("no render slot available within the queue timeout") from None
        try:
            return await asyncio.wait_for(self._do_render(html), timeout=self._render_timeout)
        except TimeoutError:
            raise RenderTimeout(f"render exceeded {self._render_timeout}s") from None
        finally:
            self._sem.release()

    async def _ensure_browser(self) -> Browser:  # pragma: no cover - exercised by slow tests
        """Return a connected browser, (re)launching it under a lock if needed.

        The double-check inside the lock means N concurrent requests hitting a
        crashed browser trigger exactly one relaunch, not N.
        """
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._relaunch_lock:
            if self._browser is None or not self._browser.is_connected():
                if self._browser is not None:
                    log.warning("browser disconnected; relaunching")
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
            return self._browser

    async def _do_render(self, html: str) -> bytes:  # pragma: no cover - exercised by slow tests
        """One isolated browser context per request; all network blocked."""
        browser = await self._ensure_browser()
        try:
            context = await browser.new_context(
                viewport={"width": self._viewport_width, "height": self._viewport_height},
                device_scale_factor=self._device_scale_factor,
            )
        except PlaywrightError as exc:
            raise RenderError(f"failed to create browser context: {exc}") from exc
        try:
            # SSRF mitigation: abort every request the page makes. Safe because
            # the page HTML inlines all assets (nothing legitimate to fetch).
            await context.route("**/*", _abort_route)
            page = await context.new_page()
            await page.set_content(html)
            await self._wait_until_ready(page)
            chart_element = page.locator(CHART_LOCATOR).first
            if await chart_element.count() > 0:
                return await chart_element.screenshot()
            return await page.screenshot()
        except PlaywrightError as exc:
            raise RenderError(f"browser render failed: {exc}") from exc
        finally:
            await context.close()

    async def _wait_until_ready(self, page: Page) -> None:  # pragma: no cover - exercised by slow tests
        """Wait for the page to finish rendering the chart.

        networkidle is provisional (heuristic, discouraged by Playwright's own
        docs): isolated here so it can be swapped for wait_for_selector /
        wait_for_function once the Design System exposes a render-complete
        signal.
        """
        await page.wait_for_load_state("networkidle")


async def _abort_route(route: Route) -> None:  # pragma: no cover - exercised by slow tests
    await route.abort()
