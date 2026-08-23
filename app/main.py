"""FastAPI application entrypoint: app creation, lifespan, router registration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.config import get_settings
from app.logging import configure_logging, get_logger
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
    log.info("service started", version=VERSION, s3_bucket=settings.s3_bucket)
    yield
    log.info("service stopping")


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
