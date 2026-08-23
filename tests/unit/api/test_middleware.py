from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
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


# --- Correlation ID middleware ---------------------------------------------


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
