import tomllib

import pytest

from app.version import SERVICE_NAME, _read_build_time
from tests.helpers import REPO_ROOT, run_python

PYPROJECT_VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_service_name_read_from_pyproject():
    """The service name comes from pyproject.toml."""
    assert SERVICE_NAME == "design-system-chart-exporter"


def test_read_build_time_set(monkeypatch):
    """A BUILD_TIME unix timestamp is converted to an ISO 8601 string."""
    monkeypatch.setenv("BUILD_TIME", "0")
    assert _read_build_time() == "1970-01-01T00:00:00.000Z"


def test_read_build_time_unset(monkeypatch):
    """An unset BUILD_TIME results in an empty string."""
    monkeypatch.delenv("BUILD_TIME", raising=False)
    assert _read_build_time() == ""


def test_read_build_time_invalid(monkeypatch):
    """A non-numeric BUILD_TIME results in an empty string."""
    monkeypatch.setenv("BUILD_TIME", "not-a-timestamp")
    assert _read_build_time() == ""


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"GIT_TAG": "v1.2.3", "GIT_COMMIT": "abc123"}, "v1.2.3"),
        ({"GIT_COMMIT": "abc123"}, "abc123"),
        ({"GIT_TAG": "", "GIT_COMMIT": ""}, PYPROJECT_VERSION),
        ({}, PYPROJECT_VERSION),
    ],
)
def test_version_prefers_tag_then_commit_then_pyproject(env, expected):
    assert run_python("from app.version import VERSION; print(VERSION)", env) == expected


def test_build_time_is_read_from_the_environment_at_import():
    assert (
        run_python("from app.version import BUILD_TIME; print(BUILD_TIME)", {"BUILD_TIME": "0"})
        == "1970-01-01T00:00:00.000Z"
    )
