import json

import pytest
import structlog

import app.logging as logging_module
from app.logging import (
    _add_exception_info,
    _add_severity,
    _add_spec_version,
    _get_renderer,
    configure_logging,
    get_logger,
)


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


def test_add_spec_version_defaults_to_v1():
    event_dict = _add_spec_version(logger=None, method_name="info", event_dict={})

    assert event_dict["spec_version"] == "v1"


def test_add_spec_version_leaves_existing_value_untouched():
    event_dict = _add_spec_version(logger=None, method_name="info", event_dict={"spec_version": "v2"})

    assert event_dict["spec_version"] == "v2"


def test_add_exception_info_leaves_event_dict_unchanged_without_exc_info():
    event_dict = {"event": "something happened"}

    result = _add_exception_info(logger=None, method_name="info", event_dict=event_dict)

    assert result == {"event": "something happened"}


def test_add_exception_info_formats_exception_instance():
    with pytest.raises(ValueError) as exc_info:
        raise ValueError("bad thing")

    event_dict = _add_exception_info(logger=None, method_name="error", event_dict={"exc_info": exc_info.value})

    assert "exc_info" not in event_dict
    errors = event_dict["errors"]
    assert len(errors) == 1
    assert errors[0]["message"] == "ValueError: bad thing"
    assert errors[0]["stack_trace"][-1]["function"] == "test_add_exception_info_formats_exception_instance"
    assert errors[0]["stack_trace"][-1]["line"] == exc_info.value.__traceback__.tb_lineno


def test_add_exception_info_formats_current_exception_when_exc_info_true():
    try:
        raise ValueError("bad thing")
    except ValueError:
        event_dict = _add_exception_info(logger=None, method_name="error", event_dict={"exc_info": True})
        errors = event_dict["errors"]
        assert errors[0]["message"] == "ValueError: bad thing"
        assert all({"file", "function", "line"} == frame.keys() for frame in errors[0]["stack_trace"])


def test_get_logger_emits_dp_standard_compliant_json(capsys):
    configure_logging(renderer=structlog.processors.JSONRenderer())
    log = get_logger(namespace="test-service")

    log.info("something happened")

    logged = json.loads(capsys.readouterr().out)
    assert logged["namespace"] == "test-service"
    assert logged["event"] == "something happened"
    assert logged["severity"] == 3
    assert logged["spec_version"] == "v1"
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


def test_get_logger_logs_dp_standard_compliant_errors_on_exception(capsys):
    configure_logging(renderer=structlog.processors.JSONRenderer())
    log = get_logger(namespace="test-service")

    try:
        raise ValueError("bad thing happened")
    except ValueError as exc:
        raise_line = exc.__traceback__.tb_lineno
        log.exception("failed")

    logged = json.loads(capsys.readouterr().out)
    assert logged["errors"] == [
        {
            "message": "ValueError: bad thing happened",
            "stack_trace": [
                {
                    "file": __file__,
                    "function": "test_get_logger_logs_dp_standard_compliant_errors_on_exception",
                    "line": raise_line,
                }
            ],
        }
    ]


def test_get_logger_with_custom_renderer(capsys):
    class CustomRenderer:
        def __call__(self, _, __, event_dict):
            return f"Custom log: {event_dict['event']}"

    configure_logging(renderer=CustomRenderer())
    log = get_logger(namespace="test-service")

    log.info("custom event")

    output = capsys.readouterr().out.strip()
    assert output == "Custom log: custom event"
