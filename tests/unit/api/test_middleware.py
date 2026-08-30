from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.api.middleware import BodySizeLimitMiddleware, CorrelationIdMiddleware
from app.config import get_settings
from app.logging import trace_id_var
from app.main import app

EXPECTED_413 = {"errors": [{"code": "request_body_too_large", "description": "Request body must not exceed 64 bytes."}]}


@pytest.fixture()
def client_64_byte_cap(monkeypatch):
    """A client whose app is configured with a tiny 64-byte body cap."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP", "false")
    monkeypatch.setenv("CHART_EXPORTER_MAX_BODY_BYTES", "64")

    get_settings.cache_clear()

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_oversized_content_length_returns_413(client_64_byte_cap):
    """An honest Content-Length above the cap is rejected before reading the body."""
    response = client_64_byte_cap.post("/charts", content=b"x" * 100, headers={"content-type": "application/json"})

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json() == EXPECTED_413


def test_oversized_chunked_body_returns_413(client_64_byte_cap):
    """With chunked encoding there is no Content-Length: the streamed count catches it."""

    def body_chunks():
        for _ in range(10):
            yield b"x" * 32

    response = client_64_byte_cap.post("/charts", content=body_chunks(), headers={"content-type": "application/json"})

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json() == EXPECTED_413


def test_body_within_cap_passes_through(client_64_byte_cap):
    """A small body sails through the middleware to normal request handling."""
    response = client_64_byte_cap.post(
        "/charts", content=b'{"language": "en"}', headers={"content-type": "application/json"}
    )

    # 400 (validation), not 413: the middleware let the request through
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_requests_without_body_are_unaffected(client_64_byte_cap):
    """GET /health has no body and must be untouched by the cap."""
    response = client_64_byte_cap.get("/health")

    # 500 CRITICAL (no browser in fast tests) — but not a 413
    assert response.status_code != HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json()["status"] == "CRITICAL"


# Correlation ID middleware
def test_generates_request_id_when_absent(client):
    response = client.get("/health")

    # Generated IDs are uuid4().hex: 32 lowercase hex characters
    assert len(response.headers["x-request-id"]) == 32
    assert all(c in "0123456789abcdef" for c in response.headers["x-request-id"])


def test_echoes_caller_supplied_request_id(client):
    response = client.get("/health", headers={"X-Request-Id": "wagtail-req-42"})

    assert response.headers["x-request-id"] == "wagtail-req-42"


def test_replaces_unsafe_request_id(client):
    """Unsafe inbound values (log injection, oversized) are replaced, not echoed."""
    response = client.get("/health", headers={"X-Request-Id": "x" * 200})

    assert response.headers["x-request-id"] != "x" * 200
    assert len(response.headers["x-request-id"]) == 32


def test_error_responses_carry_request_id(client):
    """The middleware is outermost: even 404 error documents carry the header."""
    response = client.get("/nope", headers={"X-Request-Id": "trace-me"})

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.headers["x-request-id"] == "trace-me"


# Boundaries and pure-ASGI behaviour
def _scope(headers):
    return {"type": "http", "method": "POST", "path": "/charts", "headers": headers}


async def _receive_empty():
    return {"type": "http.request", "body": b"", "more_body": False}


class _Sink:
    """Collects ASGI send() messages."""

    def __init__(self):
        self.messages = []

    async def __call__(self, message):
        self.messages.append(message)

    @property
    def status(self):
        return self.messages[0]["status"]

    @property
    def headers(self):
        return self.messages[0]["headers"]


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


@pytest.mark.parametrize(
    ("size", "expected"), [(64, HTTPStatus.BAD_REQUEST), (65, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)]
)
def test_body_size_cap_is_inclusive(client_64_byte_cap, size, expected):
    """Exactly the cap passes (then fails validation as garbage JSON); one byte over is 413."""
    response = client_64_byte_cap.post("/charts", content=b"x" * size, headers={"content-type": "application/json"})

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("size", "expected"), [(64, HTTPStatus.BAD_REQUEST), (65, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)]
)
def test_chunked_body_size_cap_is_inclusive(client_64_byte_cap, size, expected):
    def body_chunks():
        yield b"x" * 32
        yield b"x" * (size - 32)

    response = client_64_byte_cap.post("/charts", content=body_chunks(), headers={"content-type": "application/json"})

    assert response.status_code == expected


@pytest.fixture()
def cap_64(monkeypatch):
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("CHART_EXPORTER_MAX_BODY_BYTES", "64")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_oversized_content_length_never_reads_the_body(cap_64):
    """The fast path rejects on the header alone: receive() is never called, the app never runs."""

    async def receive_must_not_be_called():
        raise AssertionError("body was read")

    async def app_must_not_run(scope, receive, send):
        raise AssertionError("app ran")

    sink = _Sink()
    # Neighbouring headers sort before and after "content-length": the lookup must match by equality
    headers = [(b"accept", b"*/*"), (b"content-length", b"100"), (b"host", b"testserver")]
    await BodySizeLimitMiddleware(app_must_not_run)(_scope(headers), receive_must_not_be_called, sink)

    assert sink.status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


async def test_non_numeric_content_length_falls_through_to_streaming(cap_64):
    """A malformed Content-Length is ignored rather than crashing; the streamed count still applies."""
    sink = _Sink()
    await BodySizeLimitMiddleware(_ok_app)(_scope([(b"content-length", b"abc")]), _receive_empty, sink)

    assert sink.status == HTTPStatus.OK


async def test_non_http_scopes_pass_through_both_middlewares():
    called = []

    async def inner(scope, receive, send):
        called.append(scope["type"])

    await BodySizeLimitMiddleware(inner)({"type": "lifespan"}, _receive_empty, _Sink())
    await CorrelationIdMiddleware(inner)({"type": "lifespan"}, _receive_empty, _Sink())

    assert called == ["lifespan", "lifespan"]


async def test_trace_id_is_set_during_the_request_and_reset_after():
    seen = {}

    async def inner(scope, receive, send):
        seen["trace_id"] = trace_id_var.get()
        await _ok_app(scope, receive, send)

    sink = _Sink()
    await CorrelationIdMiddleware(inner)(_scope([(b"x-request-id", b"abc-123")]), _receive_empty, sink)

    assert seen["trace_id"] == "abc-123"
    assert trace_id_var.get() is None
    assert (b"x-request-id", b"abc-123") in sink.headers


async def test_trace_id_is_reset_even_when_the_app_raises():
    async def inner(scope, receive, send):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await CorrelationIdMiddleware(inner)(_scope([(b"x-request-id", b"abc")]), _receive_empty, _Sink())

    assert trace_id_var.get() is None


def test_413_fast_path_carries_request_id(client_64_byte_cap):
    """Correlation is the outermost layer: even the pre-routing 413 echoes the header."""
    response = client_64_byte_cap.post(
        "/charts", content=b"x" * 100, headers={"content-type": "application/json", "X-Request-Id": "trace-413"}
    )

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.headers["x-request-id"] == "trace-413"


@pytest.mark.parametrize(("length", "echoed"), [(128, True), (129, False)])
def test_request_id_length_boundary(client, length, echoed):
    value = "a" * length

    response = client.get("/health", headers={"X-Request-Id": value})

    assert (response.headers["x-request-id"] == value) is echoed


@pytest.mark.parametrize("value", ["bad value", "new\nline", "tab\tbed", "<script>", "", "a" * 129])
def test_request_ids_with_unsafe_characters_are_replaced(client, value):
    response = client.get("/health", headers={"X-Request-Id": value})

    assert response.headers["x-request-id"] != value
    assert len(response.headers["x-request-id"]) == 32


def test_request_id_lookup_matches_the_header_by_name(client):
    """Other X- headers around it must not be mistaken for X-Request-Id."""
    response = client.get("/health", headers={"X-Zzz": "other", "X-Request-Id": "abc-123", "X-Aaa": "another"})

    assert response.headers["x-request-id"] == "abc-123"
