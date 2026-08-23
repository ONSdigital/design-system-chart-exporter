"""The one end-to-end test: real browser + real Floci, single happy path.

POST a valid payload -> 201 -> the object is retrievable from Floci and its
actual PNG dimensions match the response metadata. Requires the compose
stack (`make up`) and the Playwright Chromium install; marked e2e.
"""

import json
import socket
from http import HTTPStatus
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.png import read_png_dimensions

FLOCI_ENDPOINT = "http://localhost:4566"
BUCKET = "ons-charts"
PAYLOAD = json.loads((Path(__file__).parents[2] / "examples" / "chart-payload.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.e2e


def _floci_reachable():
    try:
        with socket.create_connection(("localhost", 4566), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture()
def e2e_client(monkeypatch):
    """The real app: lifespan launches a real browser, storage points at Floci."""
    if not _floci_reachable():
        pytest.skip("Floci is not running on localhost:4566 — start it with `make up`")
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", BUCKET)
    monkeypatch.setenv("CHART_EXPORTER_S3_ENDPOINT_URL", FLOCI_ENDPOINT)
    monkeypatch.setenv("CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    get_settings.cache_clear()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_render_and_store_end_to_end(e2e_client):
    # While the browser is up, health must be OK
    health = e2e_client.get("/health")
    assert health.status_code == HTTPStatus.OK
    assert health.json()["status"] == "OK"

    response = e2e_client.post("/charts", json=PAYLOAD)

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body["bucket"] == BUCKET
    assert body["key"] == f"charts/{body['id']}.png"

    # The object really is in Floci, with matching bytes and dimensions
    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=FLOCI_ENDPOINT)
    fetched = s3.get_object(Bucket=BUCKET, Key=body["key"])
    png = fetched["Body"].read()
    assert fetched["ContentType"] == "image/png"
    assert len(png) == body["size_bytes"]
    assert read_png_dimensions(png) == (body["width"], body["height"])
