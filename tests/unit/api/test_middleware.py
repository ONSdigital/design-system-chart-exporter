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

    assert response.status_code == HTTPStatus.OK
