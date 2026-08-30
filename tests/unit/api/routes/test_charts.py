from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.domain.exceptions import RendererBusy, RenderError, RenderTimeout, StorageError
from app.domain.models import RenderedChart
from app.main import app
from app.storage.memory import MemoryStorageBackend
from tests.helpers import CHART_CONFIG, StubExporter, StubRenderer, make_png_bytes

CHART_ID = UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

VALID_PAYLOAD = {
    "language": "en",
    "device": "desktop",
    "chart_config": {"chartType": "column", "title": "A chart"},
}


@pytest.fixture()
def tolerant_client(monkeypatch):
    """Like `client`, but returns 500 responses instead of re-raising server errors."""
    monkeypatch.setenv("CHART_EXPORTER_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("CHART_EXPORTER_LAUNCH_BROWSER_ON_STARTUP", "false")

    get_settings.cache_clear()

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_create_chart_success(client, use_exporter):
    """A valid request returns 201 with the exact agreed response envelope."""
    stub = use_exporter(
        StubExporter(
            result=RenderedChart(
                id=CHART_ID,
                key=f"charts/{CHART_ID}.png",
                size_bytes=48213,
                width=1200,
                height=640,
                created_at=datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC),
            )
        )
    )
    response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.CREATED

    assert response.json() == {
        "id": "6f9619ff-8b86-d011-b42d-00cf4fc964ff",
        "created_at": "2026-07-02T12:00:00Z",
        "bucket": "test-bucket",
        "key": "charts/6f9619ff-8b86-d011-b42d-00cf4fc964ff.png",
        "content_type": "image/png",
        "size_bytes": 48213,
        "width": 1200,
        "height": 640,
    }
    assert stub.calls == [(VALID_PAYLOAD["chart_config"], "en")]


@pytest.mark.parametrize(
    ("payload", "expected_codes"),
    [
        # Missing fields
        ({"device": "desktop", "chart_config": {"a": 1}}, ["invalid_language"]),
        ({"language": "en", "chart_config": {"a": 1}}, ["invalid_device"]),
        ({"language": "en", "device": "desktop"}, ["invalid_chart_config"]),
        # Unsupported values (MVP is en/desktop only)
        ({"language": "cy", "device": "desktop", "chart_config": {"a": 1}}, ["invalid_language"]),
        ({"language": "en", "device": "mobile", "chart_config": {"a": 1}}, ["invalid_device"]),
        # chart_config must be a non-empty object
        ({"language": "en", "device": "desktop", "chart_config": {}}, ["invalid_chart_config"]),
        ({"language": "en", "device": "desktop", "chart_config": [1, 2]}, ["invalid_chart_config"]),
        ({"language": "en", "device": "desktop", "chart_config": "nope"}, ["invalid_chart_config"]),
        # Multiple problems produce multiple error items
        ({"chart_config": {}}, ["invalid_language", "invalid_device", "invalid_chart_config"]),
        # A non-object body maps to the generic body error
        ([1, 2, 3], ["invalid_request_body"]),
    ],
)
def test_validation_errors_return_400_in_spec_format(client, payload, expected_codes):
    """FastAPI's default 422 is remapped to 400 with per-field spec error codes."""
    response = client.post("/charts", json=payload)

    assert response.status_code == HTTPStatus.BAD_REQUEST

    body = response.json()
    assert [error["code"] for error in body["errors"]] == expected_codes

    for error in body["errors"]:
        assert set(error) == {"code", "description"}
        assert error["description"]


def test_malformed_json_returns_400(client):
    """A syntactically invalid JSON body is a 400, not FastAPI's default 422."""
    response = client.post("/charts", content=b'{"language": "en",', headers={"content-type": "application/json"})

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["errors"][0]["code"] == "invalid_request_body"


@pytest.mark.parametrize("content_type", ["text/plain", "application/xml", None])
def test_wrong_content_type_returns_415_before_parsing(client, content_type):
    """The guard rejects on the header alone — even a garbage body is never parsed."""
    headers = {"content-type": content_type} if content_type else {}
    response = client.post("/charts", content=b"not json at all", headers=headers)

    assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert response.json() == {
        "errors": [{"code": "unsupported_media_type", "description": "Content-Type must be application/json."}]
    }


def test_json_content_type_with_charset_is_accepted(client, use_exporter):
    """`application/json; charset=utf-8` must not be rejected by the 415 guard."""
    use_exporter(StubExporter(error=RenderError("charset check reached the exporter")))

    response = client.post(
        "/charts",
        content=b'{"language": "en", "device": "desktop", "chart_config": {"a": 1}}',
        headers={"content-type": "application/json; charset=utf-8"},
    )

    # Reaching the exporter (and its 500 mapping) proves the guard let it through
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["errors"][0]["code"] == "render_failed"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (RenderError("chromium exploded: internal detail"), 500, "render_failed"),
        (RenderTimeout("render exceeded 15s"), 500, "render_timeout"),
        (StorageError("boto3 said: AccessDenied for bucket xyz"), 500, "storage_failed"),
    ],
)
def test_domain_errors_map_to_500_without_leaking_detail(client, use_exporter, error, expected_status, expected_code):
    """Domain exceptions become sanitised 500s; internal messages never leak."""
    use_exporter(StubExporter(error=error))

    response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == expected_status

    body = response.json()

    assert body["errors"][0]["code"] == expected_code
    assert str(error) not in response.text


def test_renderer_busy_returns_503_with_retry_after(client, use_exporter):
    """Queue saturation maps to 503 and advertises Retry-After."""
    use_exporter(StubExporter(error=RendererBusy()))

    response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["errors"][0]["code"] == "renderer_busy"

    # Default queue_timeout_seconds is 5.0
    assert response.headers["retry-after"] == "5"


def test_unexpected_exception_returns_sanitised_500(tolerant_client, use_exporter):
    """Any unhandled exception becomes the generic internal_error document."""
    use_exporter(StubExporter(error=ValueError("secret internal state")))

    response = tolerant_client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json() == {"errors": [{"code": "internal_error", "description": "An internal error occurred."}]}
    assert "secret internal state" not in response.text


def test_default_provider_runs_full_stack_with_swapped_state(client):
    """No dependency override: the real deps provider assembles the real
    ChartExportService from app.state, with the renderer and storage swapped
    for test doubles (the browser and S3 are the only fakes in this path).
    """
    app.state.renderer = StubRenderer(png=make_png_bytes(2400, 1280))
    app.state.storage = storage = MemoryStorageBackend(bucket="test-bucket")

    response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.CREATED

    body = response.json()
    chart_id = UUID(body["id"])  # server-generated, valid UUID

    assert body["key"] == f"charts/{chart_id}.png"
    assert body["bucket"] == "test-bucket"
    assert body["content_type"] == "image/png"
    assert (body["width"], body["height"]) == (2400, 1280)
    assert body["size_bytes"] == len(storage.objects[body["key"]].data)

    # The response's Retry-After-style contract details are covered elsewhere;
    # here the stored object itself is the proof
    assert storage.objects[body["key"]].content_type == "image/png"


def test_default_provider_maps_storage_fault_to_500(client):
    """Fault injection through the real exporter: storage failure -> storage_failed."""
    app.state.renderer = StubRenderer()
    app.state.storage = MemoryStorageBackend(fail_with=StorageError("injected"))

    response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.json()["errors"][0]["code"] == "storage_failed"
    assert "injected" not in response.text


def _swap_in_fakes():
    app.state.renderer = StubRenderer()
    app.state.storage = MemoryStorageBackend(bucket="test-bucket")


def test_chart_config_never_appears_in_logs(client, json_logs):
    """Security requirement: charts may contain pre-release data; no log line may carry the config."""
    sentinel = "SENTINEL-PRE-RELEASE-FIGURE-8675309"
    _swap_in_fakes()

    tainted = {**CHART_CONFIG, "title": sentinel, "series": [{"data": [1], "name": sentinel}]}
    ok = client.post("/charts", json={**VALID_PAYLOAD, "chart_config": tainted})
    bad = client.post("/charts", json={**VALID_PAYLOAD, "language": "cy", "chart_config": tainted})
    # A config that breaks templating: the RenderError message must not carry config values either
    broken = client.post("/charts", json={**VALID_PAYLOAD, "chart_config": {**tainted, "series": 42}})

    assert (ok.status_code, bad.status_code, broken.status_code) == (
        HTTPStatus.CREATED,
        HTTPStatus.BAD_REQUEST,
        HTTPStatus.INTERNAL_SERVER_ERROR,
    )
    raw, events = json_logs()
    assert any(event["event"] == "chart exported" for event in events), "log capture is not working"
    assert sentinel not in raw


def test_log_events_carry_the_request_trace_id(client, json_logs):
    """The correlation ID reaches every log event emitted while handling the request."""
    _swap_in_fakes()

    client.post("/charts", json=VALID_PAYLOAD, headers={"X-Request-Id": "trace-abc"})

    _, events = json_logs()
    exported = [event for event in events if event["event"] == "chart exported"]
    assert exported
    assert all(event["trace_id"] == "trace-abc" for event in exported)


def test_key_prefix_comes_from_settings(client_factory):
    """The provider wires settings.s3_key_prefix into the service."""
    with client_factory(s3_key_prefix="custom-prefix/") as client:
        _swap_in_fakes()

        body = client.post("/charts", json=VALID_PAYLOAD).json()

    assert body["key"] == f"custom-prefix/{body['id']}.png"


@pytest.mark.parametrize(("queue_timeout", "expected"), [("2", "2"), ("0.4", "1"), ("7.6", "8")])
def test_retry_after_derives_from_queue_timeout(client_factory, use_exporter, queue_timeout, expected):
    """Retry-After is the configured queue timeout, rounded, never below 1."""
    with client_factory(queue_timeout_seconds=queue_timeout) as client:
        use_exporter(StubExporter(error=RendererBusy()))

        response = client.post("/charts", json=VALID_PAYLOAD)

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.headers["retry-after"] == expected


def test_error_codes_are_unique_per_response(client):
    """Several problems in one field must not produce duplicate error items."""
    response = client.post("/charts", json={"language": None, "device": None, "chart_config": None})

    codes = [error["code"] for error in response.json()["errors"]]
    assert len(codes) == len(set(codes))
    assert codes == ["invalid_language", "invalid_device", "invalid_chart_config"]
