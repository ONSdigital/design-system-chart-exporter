"""Exception handlers mapping every error to the spec's error document.

The contract: ALL non-2xx responses have the shape
``{"errors": [{"code": ..., "description": ...}]}`` with client-facing
descriptions only — no exception messages, stack traces, or library errors.
Full detail goes to the logs.
"""

from collections.abc import Mapping
from typing import Final, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.domain.exceptions import RendererBusy, RenderError, RenderTimeout, StorageError
from app.logging import get_logger
from app.schemas.responses import ErrorDocument, ErrorItem

log = get_logger()


class RequestError(Exception):
    """An HTTP-level request problem detected before the route body runs.

    Raised by guards/middleware (e.g. the 415 Content-Type check) that already
    know the status code and client-facing error, unlike domain exceptions
    which are mapped here.
    """

    def __init__(self, status_code: int, code: str, description: str) -> None:
        super().__init__(description)

        self.status_code = status_code
        self.code = code
        self.description = description


def error_response(status_code: int, items: list[ErrorItem], headers: Mapping[str, str] | None = None) -> JSONResponse:
    """Build a JSON response holding the spec's error document."""
    document = ErrorDocument(errors=items)

    return JSONResponse(status_code=status_code, content=document.model_dump(), headers=headers)


_FIELD_ERRORS: Final[dict[str | int, ErrorItem]] = {
    "language": ErrorItem(code="invalid_language", description="language is required and must be 'en'."),
    "device": ErrorItem(code="invalid_device", description="device is required and must be 'desktop'."),
    "chart_config": ErrorItem(
        code="invalid_chart_config", description="chart_config is required and must be a non-empty object."
    ),
}
_BODY_ERROR: Final = ErrorItem(
    code="invalid_request_body",
    description="Request body must be a valid JSON object with language, device and chart_config.",
)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    """Remap FastAPI's default 422 (including malformed JSON) to the spec's 400.

    Each pydantic error is mapped to a spec error by the field in its location;
    anything not attributable to a field (malformed JSON, non-object body) maps
    to the generic invalid_request_body error.
    """
    validation_error = cast(RequestValidationError, exc)
    items: list[ErrorItem] = []

    for error in validation_error.errors():
        field = next((part for part in error["loc"] if part in _FIELD_ERRORS), None)
        item = _FIELD_ERRORS[field] if field is not None else _BODY_ERROR
        if item not in items:
            items.append(item)
    # Log only our mapped codes: pydantic's error entries carry the offending
    # "input", which may contain chart_config (never logged).
    log.info("request validation failed", error_codes=[item.code for item in items])

    return error_response(400, items)


async def _request_error(_: Request, exc: Exception) -> JSONResponse:
    """Render a RequestError (e.g. 415, 413) as the spec's error document."""
    error = cast(RequestError, exc)
    log.info("request rejected", status_code=error.status_code, error_code=error.code)

    return error_response(error.status_code, [ErrorItem(code=error.code, description=error.description)])


async def _render_error(_: Request, exc: Exception) -> JSONResponse:
    """A render failure is a server-side 500; detail goes to logs only."""
    log.error("chart render failed", error_code="render_failed", exc_info=exc)

    return error_response(500, [ErrorItem(code="render_failed", description="The chart could not be rendered.")])


async def _render_timeout(_: Request, exc: Exception) -> JSONResponse:
    """A render that exceeded its timeout is a server-side 500."""
    log.error("chart render timed out", error_code="render_timeout", exc_info=exc)

    return error_response(500, [ErrorItem(code="render_timeout", description="Chart rendering timed out.")])


async def _storage_error(_: Request, exc: Exception) -> JSONResponse:
    """A storage upload failure is a server-side 500; detail goes to logs only."""
    log.error("chart upload failed", error_code="storage_failed", exc_info=exc)

    return error_response(
        500, [ErrorItem(code="storage_failed", description="The rendered chart could not be stored.")]
    )


async def _renderer_busy(_: Request, exc: Exception) -> JSONResponse:  # pylint: disable=unused-argument
    """Queue saturation returns 503 with Retry-After (flagged spec extension)."""
    log.warning("render queue saturated", error_code="renderer_busy")
    retry_after = max(1, round(get_settings().queue_timeout_seconds))

    return error_response(
        503,
        [ErrorItem(code="renderer_busy", description="The service is busy rendering other charts; retry shortly.")],
        headers={"Retry-After": str(retry_after)},
    )


async def _http_exception(_: Request, exc: Exception) -> JSONResponse:
    """Wrap framework HTTPExceptions (404, 405, ...) in the spec's error document."""
    http_error = cast(StarletteHTTPException, exc)

    codes = {404: "not_found", 405: "method_not_allowed", 413: "request_body_too_large"}
    code = codes.get(http_error.status_code, "http_error")

    return error_response(
        http_error.status_code,
        [ErrorItem(code=code, description=str(http_error.detail))],
        headers=http_error.headers,
    )


async def _unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    """Last resort: any unhandled exception becomes a sanitised 500."""
    log.error("unhandled exception", error_code="internal_error", exc_info=exc)

    return error_response(500, [ErrorItem(code="internal_error", description="An internal error occurred.")])


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the app.

    Starlette resolves handlers by walking the exception's MRO, so the
    RenderTimeout handler wins over the RenderError one for timeouts even
    though RenderTimeout subclasses RenderError.
    """
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(RequestError, _request_error)
    app.add_exception_handler(RenderTimeout, _render_timeout)
    app.add_exception_handler(RenderError, _render_error)
    app.add_exception_handler(StorageError, _storage_error)
    app.add_exception_handler(RendererBusy, _renderer_busy)
    app.add_exception_handler(StarletteHTTPException, _http_exception)
    app.add_exception_handler(Exception, _unhandled_exception)
