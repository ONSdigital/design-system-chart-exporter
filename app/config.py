"""Service configuration loaded from environment variables (12-factor).

All fields are read from the environment with the ``CHART_EXPORTER_`` prefix,
e.g. ``CHART_EXPORTER_S3_BUCKET``. The template-provided variables
(``LOG_LEVEL``, ``LOG_AS_JSON``, ``WEB_PORT``, ``GIT_COMMIT``, ``BUILD_TIME``)
are deliberately NOT managed here — they follow the ONS template conventions
and are read where they are used.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for the chart exporter service.

    Instantiating this class reads and validates the environment; a missing
    required variable (``CHART_EXPORTER_S3_BUCKET``) raises a pydantic
    ``ValidationError``, which is what makes a misconfigured pod fail loudly
    on boot rather than 500 on first request.
    """

    model_config = SettingsConfigDict(env_prefix="CHART_EXPORTER_", frozen=True)

    # Storage. Credentials are deliberately absent: boto3 picks them up from
    # the standard AWS environment variables or the pod IAM role.
    s3_bucket: str
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_key_prefix: str = "charts/"
    s3_set_private_acl: bool = True

    # Rendering. device_scale_factor default is provisional (open question:
    # canonical viewport/scale for device=desktop is not yet agreed).
    design_system_version: str = "latest"
    viewport_width: int = Field(default=1200, gt=0)
    viewport_height: int = Field(default=640, gt=0)
    device_scale_factor: float = Field(default=1.0, gt=0)

    # Concurrency and limits. The semaphore bound is a memory ceiling (each
    # open render context is ~50-100MB). Timeout nesting must hold:
    # queue + render timeouts < caller's client timeout < LB idle timeout
    # (and < the gunicorn worker timeout, currently 25s).
    max_concurrent_renders: int = Field(default=4, gt=0)
    render_timeout_seconds: float = Field(default=15.0, gt=0)
    queue_timeout_seconds: float = Field(default=5.0, gt=0)
    max_body_bytes: int = Field(default=1_048_576, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings instance, reading the environment once.

    The lru_cache means the environment is read and validated exactly once per
    process; tests can call ``get_settings.cache_clear()`` to re-read after
    monkeypatching the environment.
    """
    # mypy can't know that pydantic-settings fills s3_bucket from the environment
    return Settings()  # type: ignore[call-arg]
