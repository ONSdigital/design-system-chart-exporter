"""Pure ASGI middleware enforcing the request body size cap (413).

Pure ASGI (not BaseHTTPMiddleware) because BaseHTTPMiddleware would buffer
the request, defeating the point of a streaming cap. Two layers of defence:

1. If the Content-Length header already exceeds the cap, reject immediately
   without reading anything.
2. Content-Length can lie (or be absent with chunked transfer encoding), so
   the ``receive`` channel is also wrapped to count actual bytes and abort
   once the cap is crossed. The abort is an ``HTTPException(413)``: FastAPI
   wraps arbitrary exceptions raised while parsing the body into a generic
   400, but re-raises HTTPException untouched, so this reaches the app's
   exception handlers which render the spec error document (see
   api/errors.py mapping 413 -> request_body_too_large).
"""

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_response
from app.config import get_settings
from app.schemas.responses import ErrorItem


def _description(max_bytes: int) -> str:
    return f"Request body must not exceed {max_bytes} bytes."


class BodySizeLimitMiddleware:  # pylint: disable=too-few-public-methods
    """Reject request bodies larger than settings.max_body_bytes with a 413."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Enforce the body size cap around a single request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Settings are cached (lru_cache), so this is cheap per request. Read
        # lazily rather than in __init__ so importing app.main (e.g. for the
        # OpenAPI export) needs no environment.
        max_bytes = get_settings().max_body_bytes

        declared = next((value for name, value in scope["headers"] if name == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            response = error_response(
                413, [ErrorItem(code="request_body_too_large", description=_description(max_bytes))]
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise HTTPException(status_code=413, detail=_description(max_bytes))
            return message

        await self.app(scope, limited_receive, send)
