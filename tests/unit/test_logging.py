import json

import pytest
import structlog

import app.logging as logging_module
from app.logging import _add_severity, _get_renderer, configure_logging, get_logger


@pytest.mark.parametrize(
    ("method_name", "expected_severity"),
    [
        ("critical", 0),
        ("error", 1),
        ("warning", 2),
        ("info", 3),
        ("debug", 3),
        ("unknown", 3),
    ],
)
def test_add_severity_maps_method_name_to_severity_code(method_name, expected_severity):
    event_dict = _add_severity(logger=None, method_name=method_name, event_dict={})

    assert event_dict["severity"] == expected_severity


@pytest.mark.parametrize(
    ("log_as_json", "expected_type"),
    [
        (True, structlog.processors.JSONRenderer),
        (False, structlog.dev.ConsoleRenderer),
    ],
)
def test_get_renderer_selects_renderer_based_on_log_as_json(monkeypatch, log_as_json, expected_type):
    monkeypatch.setattr(logging_module, "LOG_AS_JSON", log_as_json)

    assert isinstance(_get_renderer(), expected_type)


def test_get_logger_emits_dp_standard_compliant_json(capsys):
    configure_logging(renderer=structlog.processors.JSONRenderer())
    log = get_logger(namespace="test-service")

    log.info("something happened")

    logged = json.loads(capsys.readouterr().out)
    assert logged["namespace"] == "test-service"
    assert logged["event"] == "something happened"
    assert logged["severity"] == 3
    assert "created_at" in logged
    assert "level" not in logged


def test_get_logger_binds_namespace_across_calls(capsys):
    configure_logging(renderer=structlog.processors.JSONRenderer())
    log = get_logger(namespace="test-service")

    log.info("first event")
    log.warning("second event")

    lines = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(line)["namespace"] for line in lines] == ["test-service", "test-service"]
    assert [json.loads(line)["severity"] for line in lines] == [3, 2]


def test_get_logger_with_custom_renderer(capsys):
    class CustomRenderer:
        def __call__(self, _, __, event_dict):
            return f"Custom log: {event_dict['event']}"

    configure_logging(renderer=CustomRenderer())
    log = get_logger(namespace="test-service")

    log.info("custom event")

    output = capsys.readouterr().out.strip()
    assert output == "Custom log: custom event"
