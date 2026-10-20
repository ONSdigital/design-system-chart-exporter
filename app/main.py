"""FastAPI application entrypoint: app creation, lifespan, router registration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api.errors import register_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware, CorrelationIdMiddleware
from app.api.routes.charts import router as charts_router
from app.api.routes.health import CheckHistory
from app.api.routes.health import router as health_router
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.services.renderer import ChartRenderer
from app.storage.s3 import S3StorageBackend
from app.version import SERVICE_NAME, VERSION

configure_logging(namespace=SERVICE_NAME)
log = get_logger()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Startup and shutdown logic wrapped around the application's lifetime.

    Everything before the ``yield`` runs once per worker process before the
    first request is accepted; everything after it runs on shutdown. Loading
    settings here means a misconfigured pod (e.g. missing
    CHART_EXPORTER_S3_BUCKET) crashes the worker on boot with a loud
    ValidationError instead of surfacing as a 500 on first request.

    Later phases extend this with the Playwright browser launch/close.
    """
    settings = get_settings()

    application.state.settings = settings
    application.state.start_time = datetime.now(UTC)
    application.state.check_history = CheckHistory()

    application.state.renderer = ChartRenderer(
        viewport_width=settings.viewport_width,
        viewport_height=settings.viewport_height,
        device_scale_factor=settings.device_scale_factor,
        max_concurrent_renders=settings.max_concurrent_renders,
        render_timeout_seconds=settings.render_timeout_seconds,
        queue_timeout_seconds=settings.queue_timeout_seconds,
    )

    application.state.storage = S3StorageBackend(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        set_private_acl=settings.s3_set_private_acl,
    )

    if settings.launch_browser_on_startup:  # pragma: no cover - exercised by slow tests
        await application.state.renderer.start()
    log.info("service started", version=VERSION, s3_bucket=settings.s3_bucket)
    yield

    await application.state.renderer.stop()
    log.info("service stopping")


app = FastAPI(
    lifespan=lifespan,
    title="ONS Chart Exporter",
    version=VERSION,
    summary="Render an ONS Design System chart configuration to a PNG and store it privately.",
)

app.include_router(health_router)
app.include_router(charts_router)

app.add_middleware(BodySizeLimitMiddleware)
# Added last = outermost: even 413s and unhandled errors carry X-Request-Id
app.add_middleware(CorrelationIdMiddleware)

register_exception_handlers(app)


def custom_openapi() -> dict[str, Any]:
    """Build the OpenAPI schema, removing FastAPI's auto-added 422 responses.

    Validation failures are remapped to 400 in the spec's error document (see
    api/errors.py), so a 422 never actually occurs. Stripping it keeps the
    published schema — and clients generated from it — truthful.
    """
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        summary=app.summary,
        routes=app.routes,
    )
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    # With every 422 removed, FastAPI's auto-generated validation schemas are
    # orphaned — drop them so the published schema has no unreferenced (and
    # unbounded-array) definitions.
    component_schemas = schema.get("components", {}).get("schemas", {})
    for orphan in ("HTTPValidationError", "ValidationError"):
        component_schemas.pop(orphan, None)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[method-assign]
